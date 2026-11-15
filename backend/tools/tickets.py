"""티켓 도구: 환불·교환·취소 접수와 상담원 이관."""

from sqlalchemy.orm import Session

from backend.database.models import Inquiry, Order, Ticket

# 접수형 유형 → 티켓 종류
CATEGORY_TICKET_TYPE = {"주문 취소": "취소", "교환": "교환", "반품·환불": "환불"}


def create_ticket(db: Session, inquiry: Inquiry, ticket_type: str, reason: str, order: Order | None = None) -> Ticket:
    ticket = Ticket(inquiry_id=inquiry.id, order_id=order.id if order else None, ticket_type=ticket_type, reason=reason)
    db.add(ticket)
    db.flush()  # 티켓 번호(id)를 바로 쓰려고
    return ticket
