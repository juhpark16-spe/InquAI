"""고객 답변 알림 메일: "문의하신 내용에 답변이 등록되었습니다".

- **기본은 기록만** (MAIL_ENABLED=false): notifications 표와 서버 로그에 '보낼 메일'을 남김 (status '기록')
- MAIL_ENABLED=true + SMTP 설정(.env): 답변이 DB에 저장된 **뒤에**(커밋 후) 따로 보냄 → 메일 서버가 느리거나 실패해도
  답변 발송은 막히지 않음. 결과는 status '발송'/'실패'(error) 로 남고 문의의 처리 이력에 보임
- 예시 주소(example.com·.test 등 실제로 받을 수 없는 주소)는 보내지 않고 '건너뜀'
- MAIL_REDIRECT_TO(시연용): 모든 메일을 이 주소 하나로 보냄 (제목에 원래 받는 사람 표시). 시연 고객 주소는 가짜라서
- 보안: 본문에는 답변 내용 대신 조회 안내만 (메일이 다른 사람에게 가도 답변이 노출되지 않게). SMTP 비밀번호는 .env 에만

설정 확인 (실제로 1통 보냄, 프로젝트 루트에서):
    python -m backend.services.notify --test 받을주소@example.com
"""

import argparse
import logging
import smtplib
import ssl
import sys
import threading
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.database.models import Inquiry, Notification, utcnow

logger = logging.getLogger("inquai.notify")

SUBJECT = "[InquAI 쇼핑] 문의하신 내용에 답변이 등록되었습니다"
FAKE_DOMAINS = ("example.com", "example.org", "example.net")
FAKE_SUFFIXES = (".test", ".example", ".invalid", ".localhost")


def is_fake_address(address: str) -> bool:
    """실제로 받을 수 없는 예시 주소 (RFC 2606)"""
    domain = address.rsplit("@", 1)[-1].lower()
    return domain in FAKE_DOMAINS or domain.endswith(FAKE_SUFFIXES)


def _body(inquiry: Inquiry, shop_url: str) -> str:
    """회원 문의(조회 비밀번호 없음)는 '내 쇼핑 > 내 문의'로, 비회원 문의는 문의 조회(이메일 + 비밀번호)로 안내"""
    head = (f"{inquiry.customer_name} 고객님, 안녕하세요. InquAI 쇼핑 고객센터입니다.\n\n"
            f"문의하신 '{inquiry.title}'({inquiry.inquiry_number})에 답변이 등록되었습니다.\n")
    if inquiry.lookup_password_hash is None:   # 쇼핑몰에 로그인한 상태로 남긴 문의
        guide = f"쇼핑몰에 로그인한 뒤 '내 쇼핑 > 내 문의'에서 확인해 주세요 (비밀번호 없이 바로 보입니다).\n\n{shop_url}/my\n\n"
    else:
        guide = f"아래 주소의 문의 조회에서 이메일과 문의할 때 정한 비밀번호로 확인해 주세요.\n\n{shop_url}/inquiry/lookup\n\n"
    return head + guide + "이 메일은 발신 전용입니다."


def answer_registered(db: Session, inquiry: Inquiry) -> Notification:
    """답변 알림을 남기고, 메일이 켜져 있으면 커밋 뒤에 보내도록 예약 (커밋은 부르는 쪽에서)"""
    settings = get_settings()
    n = Notification(inquiry_id=inquiry.id, channel="email", recipient=inquiry.customer_email,
                     subject=SUBJECT, body=_body(inquiry, settings.shop_url.rstrip("/")), status="기록")
    db.add(n)
    if not settings.mail_enabled:
        logger.info("답변 알림(기록만) → %s: %s", inquiry.customer_email, inquiry.inquiry_number)
        return n
    to = settings.mail_redirect_to or inquiry.customer_email
    if is_fake_address(to):
        n.status, n.error = "건너뜀", "예시 주소라 보내지 않음 (시연용 받는 주소 MAIL_REDIRECT_TO 를 정하면 그 주소로 보냄)"
        return n
    n.status = "대기"
    db.flush()   # 번호(id)를 정해 둠 → 커밋 뒤 결과를 이 기록에 남김
    outbox = db.info.setdefault("mail_outbox", [])
    outbox.append((n.id, to, n.subject + ("" if to == inquiry.customer_email else f" (원래 받는 사람: {inquiry.customer_email})"),
                   n.body))
    if not db.info.get("mail_hooked"):
        db.info["mail_hooked"] = True
        event.listen(db, "after_commit", _after_commit)
        event.listen(db, "after_rollback", lambda s: s.info.pop("mail_outbox", None))
    return n


def _after_commit(session: Session) -> None:
    items = session.info.pop("mail_outbox", None)
    if items:   # 응답을 기다리게 하지 않도록 따로 (서버 1대 기준의 단순한 방식, 실패해도 다시 보내지는 않음)
        run_later(lambda: deliver(items))


def run_later(job) -> None:
    """테스트에서는 바로 실행하도록 바꿈"""
    threading.Thread(target=job, daemon=True, name="mail").start()


def smtp_send(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((s.mail_from_name, s.mail_from or s.smtp_user))
    msg["To"] = to
    msg.set_content(body)
    context = ssl.create_default_context()
    if s.smtp_port == 465:   # SSL 바로 연결 (Gmail 465 등)
        with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=context, timeout=15) as server:
            server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)
    else:                    # 587: 연결 후 STARTTLS
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
            server.starttls(context=context)
            server.login(s.smtp_user, s.smtp_password)
            server.send_message(msg)


def deliver(items: list[tuple[int, str, str, str]]) -> None:
    """메일을 보내고 결과를 기록 (요청과 다른 DB 세션)"""
    from backend.database.session import SessionLocal

    for notification_id, to, subject, body in items:
        try:
            smtp_send(to, subject, body)
            status, error = "발송", None
            logger.info("답변 알림 메일 발송 → %s", to)
        except Exception as e:  # noqa: BLE001  메일 실패는 답변 처리에 영향을 주지 않음
            status, error = "실패", f"{type(e).__name__}: {e}"[:200]
            logger.warning("답변 알림 메일 실패 → %s: %s", to, error)
        with SessionLocal() as db:
            n = db.get(Notification, notification_id)
            if n is not None:
                n.status, n.error, n.sent_at = status, error, utcnow()
                db.commit()


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="메일 설정 확인 (실제로 1통 보냄)")
    p.add_argument("--test", required=True, metavar="받을주소", help="확인 메일을 받을 주소")
    args = p.parse_args()
    s = get_settings()
    missing = [k for k in ("smtp_host", "smtp_user", "smtp_password") if not getattr(s, k)]
    if missing:
        raise SystemExit(f".env 에 {', '.join(k.upper() for k in missing)} 를 넣어 주세요 (.env.example 참고)")
    smtp_send(args.test, "[InquAI 쇼핑] 메일 설정 확인", "InquAI 메일 설정이 잘 되었습니다. 이 메일은 확인용입니다.")
    print(f"보냈습니다 → {args.test} (MAIL_ENABLED={s.mail_enabled}: true 여야 답변 알림이 실제로 나갑니다)")


if __name__ == "__main__":
    main()
