"""주문 도구: 본인 주문 확인, 배송 조회 (최소 버전. 3주차에 취소·반품 가능 여부 판단을 더함)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database.models import Customer, Order, as_utc


def find_customer_order(db: Session, order_number: str, email: str) -> Order | None:
    """주문번호와 주문한 고객의 이메일이 모두 맞을 때만 주문을 돌려줍니다 (기획서 2-4 본인 확인)."""
    return db.scalar(select(Order).join(Customer)
                     .where(Order.order_number == order_number, func.lower(Customer.email) == email.lower()))


def shipping_summary(order: Order) -> dict:
    delivered = as_utc(order.delivered_at)
    return {
        "order_number": order.order_number,
        "product_name": order.product_name,
        "order_status": order.order_status,
        "shipping_status": order.shipping_status,
        "tracking_number": order.tracking_number,
        "delivered_at": delivered.isoformat() if delivered else None,
    }
