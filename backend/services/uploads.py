"""고객 사진 첨부: 검사·저장·문의 연결.

- 사진만 받음 (JPEG·PNG·WEBP). 확장자·브라우저가 보낸 형식은 믿지 않고 파일 앞부분(매직 바이트)으로 확인
- 1장 5MB, 문의 1건에 3장까지. 저장 이름은 무작위라 원래 파일 이름으로 다른 파일을 덮어쓸 수 없음
- 저장 위치 data/uploads/ 는 Git에 올리지 않음 (개인정보가 담긴 사진일 수 있음)
- 올린 뒤 1시간 안에 문의에 연결되지 않은 사진은 연결할 수 없음
"""

import hashlib
import hmac
import secrets
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.config import PROJECT_ROOT, get_settings
from backend.core.errors import AppError
from backend.database.models import Attachment, as_utc, utcnow

UPLOAD_DIR = PROJECT_ROOT / "data" / "uploads"
MAX_BYTES = 5 * 1024 * 1024
MAX_FILES = 3
CLAIM_WINDOW = timedelta(hours=1)

# 파일 앞부분으로 형식 판별 → (content-type, 확장자)
def sniff_image(head: bytes) -> tuple[str, str] | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def save_upload(db: Session, filename: str, data: bytes) -> Attachment:
    if len(data) == 0:
        raise AppError(400, "빈 파일입니다.", "INVALID_FILE")
    if len(data) > MAX_BYTES:
        raise AppError(400, "사진은 한 장에 5MB까지 올릴 수 있습니다.", "FILE_TOO_LARGE")
    kind = sniff_image(data[:16])
    if kind is None:
        raise AppError(400, "사진(JPG, PNG, WEBP)만 올릴 수 있습니다.", "INVALID_FILE")
    content_type, ext = kind
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    path = UPLOAD_DIR / f"{secrets.token_hex(16)}.{ext}"
    path.write_bytes(data)
    stored = path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path  # 테스트는 임시 폴더
    att = Attachment(token=token, filename=Path(filename or "photo").name[:200], content_type=content_type,
                     size=len(data), path=str(stored))
    db.add(att)
    db.commit()
    return att


def claim(db: Session, tokens: list[str], inquiry_id: int, message_id: int | None = None) -> list[Attachment]:
    """업로드 token 을 문의(또는 추가 문의)에 연결. 이미 연결됐거나 오래된 token 은 400"""
    if not tokens:
        return []
    if len(tokens) > MAX_FILES or len(set(tokens)) != len(tokens):
        raise AppError(400, f"사진은 {MAX_FILES}장까지 올릴 수 있습니다.", "TOO_MANY_FILES")
    rows = db.scalars(select(Attachment).where(Attachment.token.in_(tokens))).all()
    now = utcnow()
    if len(rows) != len(tokens) or any(a.inquiry_id is not None or now - as_utc(a.created_at) > CLAIM_WINDOW
                                       for a in rows):
        raise AppError(400, "첨부한 사진을 찾을 수 없습니다. 사진을 다시 올려 주세요.", "INVALID_FILE")
    for a in rows:
        a.inquiry_id, a.message_id = inquiry_id, message_id
    return rows


LINK_MINUTES = 30


def _sig(attachment_id: int, exp: int) -> str:
    key = get_settings().jwt_secret_key.encode()
    return hmac.new(key, f"attachment:{attachment_id}:{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def public_url(att: Attachment) -> str:
    """고객이 자기 사진을 볼 수 있는 30분짜리 서명 주소.

    고객은 로그인 쿠키가 없어 <img> 로 사진을 부를 때 본인 확인을 할 수 없으므로, 본인 확인(이메일+비밀번호)을
    통과한 조회 응답에만 서명된 주소를 넣어 줍니다. 주소를 모르거나 30분이 지나면 볼 수 없습니다.
    """
    exp = int(time.time()) + LINK_MINUTES * 60
    return f"/api/inquiries/attachments/{att.id}?exp={exp}&sig={_sig(att.id, exp)}"


def verify_link(attachment_id: int, exp: int, sig: str) -> bool:
    return exp >= time.time() and hmac.compare_digest(_sig(attachment_id, exp), sig)


def file_path(att: Attachment) -> Path:
    p = Path(att.path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def purge_unclaimed(db: Session) -> int:
    """올렸지만 문의에 연결되지 않은 채 연결 가능 시간(1시간)이 지난 사진: 파일과 기록을 지움 (개인정보·디스크).
    서버가 켜질 때 부름 (main.lifespan). 지운 수를 돌려줌, 커밋은 부르는 쪽에서"""
    cutoff = utcnow() - CLAIM_WINDOW
    rows = [a for a in db.scalars(select(Attachment).where(Attachment.inquiry_id.is_(None)))
            if as_utc(a.created_at) < cutoff]
    for a in rows:
        try:
            file_path(a).unlink(missing_ok=True)
        except OSError:
            continue   # 지우지 못한 파일은 기록을 남겨 다음에 다시
        db.delete(a)
    return len(rows)
