"""티켓 처리 API (로그인, docs/api_spec.md 6장, 4주차 구현): AI가 접수한 취소·교환·환불 티켓을 상담원이 승인·반려합니다.

    PATCH /api/tickets/{id}   { "status": "승인" | "반려", "memo": "..." }

- 권한: 관리자, 또는 그 문의를 배정받은 상담원.
- 취소 승인은 출고 전 주문(결제 완료·상품 준비 중)만 → 주문 상태를 '취소'로 바꿉니다. 이미 나간 주문은 409 (반려 후 반품 안내).
- 취소 승인은 결제 내역에 '승인 취소'를, 환불 승인은 '환불 예정'(3영업일)을 남깁니다 (주문 정보 카드에 보임).
  실제 회수·환불 처리는 쇼핑몰 시스템의 일이라 시연에서는 기록만 합니다.
- 반려는 사유(memo)가 필요합니다. 처리 결과는 작업 기록(ticket_approve / ticket_reject)과 문의 처리 이력에 남고,
  [AI 초안 다시 만들기]를 누르면 초안 근거(처리 기록)에 결과가 들어갑니다.
"""

from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from backend.api.inquiry_admin import get_inquiry_for_user
from backend.core.dependencies import DB, LoginUser
from backend.core.errors import AppError
from backend.database.models import AdminAuditLog, Order, Payment, Ticket, utcnow
from backend.schemas.inquiry_admin import TicketOut
from backend.services import inventory
from backend.services.audit import add_audit

RETURN_FEE = 6000   # 단순 변심 반품 왕복 배송비 (docs/shop_policy.md, services/order_actions.py 의 반품 접수 안내와 같음)


def _return_reason(db, order_number: str) -> str | None:
    """상담원이 [반품 회수 접수]로 남긴 반품 사유 (가장 최근 것, 작업 기록에서)"""
    rows = db.scalars(select(AdminAuditLog).where(AdminAuditLog.action == "order_action")
                      .order_by(AdminAuditLog.id.desc())).all()
    for a in rows:
        d = a.detail or {}
        if d.get("kind") == "return" and d.get("order_number") == order_number:
            return (d.get("after") or {}).get("reason")
    return None


router = APIRouter(prefix="/tickets", tags=["티켓 처리"])
ACTIONABLE = ("취소", "교환", "환불")
CANCELLABLE = ("결제 완료", "상품 준비 중")   # 출고 전 (docs/shop_policy.md: 취소는 출고 전만)


class TicketDecision(BaseModel):
    status: Literal["승인", "반려"]
    memo: str | None = Field(None, max_length=500)

    @field_validator("memo")
    @classmethod
    def _strip(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v


@router.patch("/{ticket_id}", response_model=TicketOut, summary="티켓 승인·반려 (로그인)")
def decide(ticket_id: int, body: TicketDecision, request: Request, user: LoginUser, db: DB):
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise AppError(404, "티켓을 찾을 수 없습니다.", "NOT_FOUND")
    inquiry = get_inquiry_for_user(db, ticket.inquiry_id, user)   # 배정된 상담원·관리자만
    if ticket.ticket_type not in ACTIONABLE:
        raise AppError(422, f"{ticket.ticket_type} 티켓은 승인·반려 대상이 아닙니다.", "INVALID_STATE")
    if ticket.status != "접수":
        raise AppError(409, f"이미 {ticket.status}된 티켓입니다.", "TICKET_DONE")
    if body.status == "반려" and not body.memo:
        raise AppError(422, "반려 사유를 적어 주세요.", "VALIDATION_ERROR")

    order = db.get(Order, ticket.order_id) if ticket.order_id else None
    if order is None and inquiry.order_number:   # 주문번호를 나중에 받은 문의 (예전 티켓)
        order = db.scalar(select(Order).where(Order.order_number == inquiry.order_number))
        ticket.order_id = order.id if order else None
    order_change = None
    if body.status == "승인" and ticket.ticket_type == "취소":
        if order is None:
            raise AppError(409, "연결된 주문이 없어 취소할 수 없습니다. 주문번호를 확인해 주세요.", "INVALID_STATE")
        if order.order_status not in CANCELLABLE:
            raise AppError(409, f"이미 '{order.order_status}' 상태라 취소할 수 없습니다. 반려하고 반품으로 안내해 주세요.",
                           "INVALID_STATE")
        order_change = {"order_number": order.order_number, "before": order.order_status, "after": "취소"}
        order.order_status, order.shipping_status = "취소", None
        inventory.restock(db, order.product_name, order.quantity or 1)   # 취소한 수량은 재고로
        # 결제 내역에 승인 취소 (카드는 3~5영업일 안에 반영, 주문 정보 카드의 '결제·환불 내역'에 보임)
        db.add(Payment(order_id=order.id, kind="승인 취소", method=order.payment_method, amount=order.amount,
                       at=utcnow(), memo="주문 취소 (티켓 승인)"))
    if body.status == "승인" and ticket.ticket_type == "환불" and order is not None:
        # 환불 예정 (실제 환불은 쇼핑몰 결제 시스템의 일. 상담원이 고객에게 예정일을 안내할 수 있게 기록)
        if order.order_status == "취소":
            raise AppError(409, "이미 취소된 주문이라 결제가 승인 취소로 처리됐어요. 환불 티켓은 반려해 주세요.", "INVALID_STATE")
        if any(p.kind == "환불" for p in order.payments):
            raise AppError(409, "이 주문에는 이미 환불(예정)이 있어요. 결제·환불 내역을 확인해 주세요.", "ALREADY_REFUNDED")
        amount, memo = order.amount, "반품 회수·검수 후 3영업일 이내 (티켓 승인)"
        if _return_reason(db, order.order_number) == "단순 변심":   # [반품 회수 접수]에서 안내한 대로 왕복 배송비 차감
            amount, memo = max(order.amount - RETURN_FEE, 0), memo + f" · 단순 변심 왕복 배송비 {RETURN_FEE:,}원 차감"
        db.add(Payment(order_id=order.id, kind="환불", status="예정", method=order.payment_method, amount=amount,
                       at=utcnow() + timedelta(days=3), memo=memo))

    ticket.status, ticket.memo = body.status, body.memo
    ticket.handled_by, ticket.handled_at = user.id, utcnow()
    add_audit(db, request, "ticket_approve" if body.status == "승인" else "ticket_reject", user, "inquiry", inquiry.id,
              ticket_id=ticket.id, ticket_type=ticket.ticket_type, memo=body.memo, order=order_change)
    db.commit()
    return ticket
