"""단순 변심 교환 배송비 (왕복 6,000원) 받기 (2026-11-26, docs/shop_policy.md 교환 배송비).

반품은 환불 금액에서 빼면 되지만, 교환은 돌려줄 돈이 없어 따로 받아야 함. 방법은 두 가지:
- 적립금으로 차감: 상담원 바로 처리 [교환 배송비 받기 → 적립금으로] (잔액 6,000원 이상, 고객 동의 후)
- 결제 요청: 상담원이 [결제 요청]을 보내면 고객 문의 화면(내 쇼핑 > 내 문의 / 문의 조회)에 [교환 배송비 결제] 버튼
  → 카드·간편결제로 결제 (시연: 실제 결제 없이 승인번호를 만들어 기록)
결제가 확인되면 상담원이 회수를 접수하고 교환을 승인. 불량·오배송 교환은 쇼핑몰 부담이라 받지 않음.

새 표 없이 결제 내역(payments)에 '추가 결제' 한 줄로 남김: status 요청(고객 결제 대기) → 완료.
"""

import random

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.errors import AppError
from backend.database.models import Customer, Inquiry, Order, Payment, as_utc, utcnow
from backend.services.policy import RETURN_FEE

KIND = "추가 결제"
MEMO = "교환 배송비 (단순 변심 왕복)"
PAY_METHODS = ("신용카드", "간편결제")   # 고객이 결제 요청에 결제할 때


def fee_row(order: Order) -> Payment | None:
    return next((p for p in order.payments if p.kind == KIND and (p.memo or "").startswith("교환 배송비")), None)


def state(order: Order | None) -> dict | None:
    """화면용: {amount, status(요청/완료), method, at} 또는 None(아직 받지 않음)"""
    row = fee_row(order) if order else None
    if row is None:
        return None
    return {"amount": row.amount, "status": row.status, "method": row.method, "at": as_utc(row.at)}


def order_for(db: Session, inquiry: Inquiry) -> Order | None:
    """문의에 적힌 본인 주문 (주문자 이메일 = 문의 이메일일 때만)"""
    if not inquiry.order_number:
        return None
    row = db.execute(select(Order, Customer).join(Customer).where(Order.order_number == inquiry.order_number)).first()
    if row is None or row[1].email.lower() != inquiry.customer_email.lower():
        return None
    return row[0]


def request(db: Session, order: Order) -> Payment:
    if fee_row(order) is not None:
        raise AppError(409, "이미 교환 배송비를 요청했거나 받았습니다.", "INVALID_STATE")
    row = Payment(order_id=order.id, kind=KIND, status="요청", method=None, amount=RETURN_FEE, at=utcnow(), memo=MEMO)
    db.add(row)
    order.payments.append(row)
    return row


def take_points(db: Session, order: Order, customer: Customer, balance: int) -> Payment:
    """적립금으로 차감 (결제 요청을 보낸 뒤 고객이 적립금으로 바꿔 달라고 해도 같은 줄을 완료로)"""
    from backend.database.models import PointHistory
    row = fee_row(order)
    if row is not None and row.status == "완료":
        raise AppError(409, "이미 교환 배송비를 받았습니다.", "INVALID_STATE")
    if balance < RETURN_FEE:
        raise AppError(409, f"적립금이 부족합니다 (잔액 {balance:,}원, 필요 {RETURN_FEE:,}원). 결제 요청을 보내 주세요.", "INVALID_STATE")
    now = utcnow()
    db.add(PointHistory(customer_id=customer.id, amount=-RETURN_FEE, reason="교환 배송비 차감", at=now, order_number=order.order_number))
    if row is None:
        row = Payment(order_id=order.id, kind=KIND, amount=RETURN_FEE, memo=MEMO, at=now)
        db.add(row)
        order.payments.append(row)
    row.status, row.method, row.at = "완료", "적립금", now
    return row


def customer_pay(db: Session, inquiry: Inquiry, method: str) -> dict:
    """고객이 문의 화면에서 결제 (요청된 것만). 시연이라 실제 결제 없이 승인번호를 만들어 기록"""
    if method not in PAY_METHODS:
        raise AppError(422, "결제 수단을 골라 주세요 (신용카드·간편결제).", "VALIDATION_ERROR")
    order = order_for(db, inquiry)
    row = fee_row(order) if order else None
    if row is None or row.status != "요청":
        raise AppError(409, "결제할 교환 배송비가 없습니다.", "INVALID_STATE")
    row.status, row.method, row.at = "완료", method, utcnow()
    row.approval_no = f"{random.randint(10_000_000, 99_999_999)}"
    return state(order)


def customer_for(db: Session, inquiry: Inquiry) -> Customer | None:
    return db.scalar(select(Customer).where(func.lower(Customer.email) == inquiry.customer_email.lower()))
