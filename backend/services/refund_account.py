"""환불 계좌: 무통장입금 주문을 취소·반품할 때 돈을 돌려받을 계좌 (정책 F29: 환불 계좌로 1~2영업일).

- 고객은 문의하기·추가 문의의 '환불 계좌' 칸(은행 / 예금주 / 계좌번호)으로 보냄. 문의 글에 계좌번호를 적지 않게 안내.
- 문의 글과 따로 저장(inquiries.refund_*)하고 **AI 분석·초안에는 넘기지 않음** (문의 글은 OpenAI로 보내지기 때문).
  AI 초안 입력에는 '받음 / 아직 없음'만 들어감.
- 고객 화면에는 가려서(국민은행 ****9012 · 홍*동), 상담원 화면도 가려서 보이고 [번호 보기]를 누를 때만 전체 번호 →
  그때마다 작업 기록(refund_account_view)에 남김.
- **예금주·계좌번호는 암호화해서 저장** (Fernet = AES-128-CBC + HMAC-SHA256, cryptography 패키지).
  DB 파일이 새어 나가도 번호를 읽을 수 없음. 은행 이름만 그대로 (그것만으로는 개인을 알 수 없음).
  열쇠는 .env 의 REFUND_ACCOUNT_KEY, 비어 있으면 JWT_SECRET_KEY 에서 만들어 씀 → **열쇠를 바꾸면 예전 계좌는 못 읽음**.
- 예전(암호화 전)에 평문으로 저장된 값은 서버가 켜질 때 encrypt_legacy() 가 암호화해 바꿈.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.database.models import Inquiry, utcnow
from backend.services.inquiry_context import order_card

BANKS = ("국민은행", "신한은행", "우리은행", "하나은행", "농협은행", "기업은행", "SC제일은행", "카카오뱅크", "토스뱅크", "케이뱅크",
         "새마을금고", "우체국", "수협은행", "부산은행", "대구은행", "광주은행", "경남은행", "전북은행", "씨티은행")
NEEDS_CATEGORIES = ("주문 취소", "반품·환불")


TOKEN_PREFIX = "gAAAAA"   # Fernet 암호문은 늘 이렇게 시작 (평문 계좌번호·이름과 구별)
UNREADABLE = "(열 수 없음)"   # 열쇠가 바뀌어 풀 수 없을 때


@lru_cache
def _fernet() -> Fernet:
    s = get_settings()
    if s.refund_account_key:
        return Fernet(s.refund_account_key.encode())
    if len(s.jwt_secret_key) < 32:
        raise RuntimeError(".env 의 REFUND_ACCOUNT_KEY(또는 JWT_SECRET_KEY)를 넣어 주세요.")
    # 따로 열쇠가 없으면 JWT 열쇠에서 용도별 열쇠를 만들어 씀 (같은 값을 그대로 쓰지 않게 앞에 용도 이름을 붙임)
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"inquai-refund-account:" + s.jwt_secret_key.encode()).digest()))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    """암호문 → 원래 값. 암호화 전 평문이면 그대로, 열쇠가 달라 못 풀면 UNREADABLE"""
    if not value:
        return value
    if not value.startswith(TOKEN_PREFIX):
        return value
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return UNREADABLE


def save(inquiry: Inquiry, bank: str, holder: str, number: str) -> None:
    inquiry.refund_bank = bank
    inquiry.refund_holder = encrypt(holder.strip())
    inquiry.refund_account = encrypt("".join(ch for ch in number if ch.isdigit()))   # 숫자만, 암호화해서
    inquiry.refund_account_at = utcnow()


def encrypt_legacy(db: Session) -> int:
    """암호화 전에 평문으로 저장된 환불 계좌를 암호화 (서버가 켜질 때). 바꾼 건수를 돌려줌"""
    rows = db.scalars(select(Inquiry).where(or_(Inquiry.refund_account.is_not(None), Inquiry.refund_holder.is_not(None)))).all()
    count = 0
    for inquiry in rows:
        changed = False
        for field in ("refund_account", "refund_holder"):
            value = getattr(inquiry, field)
            if value and not value.startswith(TOKEN_PREFIX):
                setattr(inquiry, field, encrypt(value))
                changed = True
        count += changed
    return count


def _mask_name(name: str) -> str:
    return name[0] + "*" * (len(name) - 2) + name[-1] if len(name) > 2 else name[0] + "*"


def masked(inquiry: Inquiry) -> dict | None:
    """가린 계좌 (고객 화면·상담원 화면 기본): 은행 · 끝 4자리 · 예금주 가운데 가림"""
    if not inquiry.refund_account:
        return None
    holder, number = decrypt(inquiry.refund_holder), decrypt(inquiry.refund_account)
    return {"bank": inquiry.refund_bank, "holder": holder if holder == UNREADABLE else _mask_name(holder or "?"),
            "number": number if number == UNREADABLE else f"****{number[-4:]}", "registered_at": inquiry.refund_account_at}


def full(inquiry: Inquiry) -> dict | None:
    """전체 계좌 (상담원이 [번호 보기]를 누를 때만, 부르는 쪽에서 작업 기록을 남김)"""
    if not inquiry.refund_account:
        return None
    return {"bank": inquiry.refund_bank, "holder": decrypt(inquiry.refund_holder), "number": decrypt(inquiry.refund_account),
            "registered_at": inquiry.refund_account_at}


def needed(db: Session, inquiry: Inquiry) -> bool:
    """환불 계좌가 필요한데 아직 없음: 무통장입금 주문 + 취소·반품 문의(또는 그 요청이 반려되지 않음)"""
    if inquiry.refund_account:
        return False
    card = order_card(db, inquiry)
    if not card or not card.get("found") or card.get("payment_method") != "무통장입금" or card.get("email_match") is False:
        return False
    asked = any(t.ticket_type in ("취소", "환불") and t.status != "반려" for t in inquiry.tickets)
    category = inquiry.analysis.category if inquiry.analysis else None
    return asked or category in NEEDS_CATEGORIES
