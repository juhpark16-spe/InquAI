"""고객 답변 알림 (시연용 기록).

실제 쇼핑몰은 알림톡·문자·이메일로 "답변이 등록되었습니다"를 보냅니다. 이 프로젝트는 메일 서버가 없어
보낼 메일을 notifications 테이블과 서버 로그에 기록만 합니다. 메일 서버를 붙이면 send() 안만 바꾸면 됩니다.
보안상 메일 본문에는 답변 내용 대신 조회 안내만 넣습니다 (메일이 다른 사람에게 가도 답변이 노출되지 않게).
"""

import logging

from sqlalchemy.orm import Session

from backend.database.models import Inquiry, Notification

logger = logging.getLogger("inquai.notify")


def answer_registered(db: Session, inquiry: Inquiry) -> Notification:
    body = (f"{inquiry.customer_name} 고객님, 문의하신 '{inquiry.title}'({inquiry.inquiry_number})에 답변이 등록되었습니다.\n"
            "고객센터 > 문의 조회에서 이메일과 문의할 때 정한 비밀번호로 확인해 주세요.")
    n = Notification(inquiry_id=inquiry.id, channel="email", recipient=inquiry.customer_email,
                     subject="[InquAI 쇼핑] 문의하신 내용에 답변이 등록되었습니다", body=body, status="기록")
    db.add(n)
    logger.info("답변 알림(시연 기록) → %s: %s", inquiry.customer_email, inquiry.inquiry_number)
    return n
