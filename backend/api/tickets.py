"""티켓 처리 API (로그인, docs/api_spec.md 6장, 4주차 구현): AI가 접수한 취소·교환·환불 티켓을 상담원이 승인·반려합니다.

    PATCH /api/tickets/{id}   { "status": "승인" | "반려", "memo": "..." }

- 권한: 관리자, 또는 그 문의를 배정받은 상담원.
- 취소 승인은 출고 전 주문(결제 완료·상품 준비 중)만 → 주문 상태를 '취소'로 바꿉니다. 이미 나간 주문은 409 (반려 후 반품 안내).
- 교환·환불 승인은 티켓만 승인합니다 (회수·환불 처리는 실제 쇼핑몰 시스템의 일, 시연에서는 기록만).
- 반려는 사유(memo)가 필요합니다. 처리 결과는 작업 기록(ticket_approve / ticket_reject)과 문의 처리 이력에 남고,
  [AI 초안 다시 만들기]를 누르면 초안 근거(처리 기록)에 결과가 들어갑니다.
"""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, field_validator

from backend.api.inquiry_admin import get_inquiry_for_user
from backend.core.dependencies import DB, LoginUser
from backend.core.errors import AppError
from backend.database.models import Order, Ticket, utcnow
from backend.schemas.inquiry_admin import TicketOut
from backend.services.audit import add_audit

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
    order_change = None
    if body.status == "승인" and ticket.ticket_type == "취소":
        if order is None:
            raise AppError(409, "연결된 주문이 없어 취소할 수 없습니다. 주문번호를 확인해 주세요.", "INVALID_STATE")
        if order.order_status not in CANCELLABLE:
            raise AppError(409, f"이미 '{order.order_status}' 상태라 취소할 수 없습니다. 반려하고 반품으로 안내해 주세요.",
                           "INVALID_STATE")
        order_change = {"order_number": order.order_number, "before": order.order_status, "after": "취소"}
        order.order_status, order.shipping_status = "취소", None

    ticket.status, ticket.memo = body.status, body.memo
    ticket.handled_by, ticket.handled_at = user.id, utcnow()
    add_audit(db, request, "ticket_approve" if body.status == "승인" else "ticket_reject", user, "inquiry", inquiry.id,
              ticket_id=ticket.id, ticket_type=ticket.ticket_type, memo=body.memo, order=order_change)
    db.commit()
    return ticket
