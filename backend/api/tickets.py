"""티켓 처리 API (로그인, docs/api_spec.md 6장, 4주차 구현): AI가 접수한 취소·교환·반품 요청(티켓)을 상담원이 승인·반려합니다.
(서버 값 ticket_type '환불'은 반품 후 환불이라 화면에서는 '반품'으로 보임)

    GET   /api/tickets          취소·교환·반품 요청 목록 (상태·종류 조건, 상태별 건수)
    GET   /api/tickets/refunds  환불 진행 (승인 뒤 환불 예정·완료, 예정일 지남 표시)
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

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from backend.api.inquiry_admin import get_inquiry_for_user
from backend.core.dependencies import DB, LoginUser
from backend.core.errors import AppError
from backend.database.models import AdminUser, Inquiry, Order, Payment, Ticket, as_utc, utcnow
from backend.schemas.inquiry_admin import TicketOut
from backend.services import inventory, sla
from backend.services import inquiry_context as ctx
from backend.services.policy import CANCELLABLE, DEFECT_RETURN_DAYS, REFUND_BUSINESS_DAYS, RETURN_FEE, SHIPPING_FEE
from backend.services.audit import add_audit



router = APIRouter(prefix="/tickets", tags=["티켓 처리"])
ACTIONABLE = ("취소", "교환", "환불")


class TicketDecision(BaseModel):
    status: Literal["승인", "반려"]
    memo: str | None = Field(None, max_length=500)
    # 반품 승인: 회수 접수 때 '단순 변심'이었지만 검수해 보니 불량이면 왕복 배송비를 빼지 않고 전액 환불 (정책 F17: 불량은 쇼핑몰 부담)
    waive_return_fee: bool = False

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
    if body.status == "승인" and order is not None and order.customer.email.lower() != inquiry.customer_email.lower():
        # 본인 확인: [바로 처리]와 같은 기준 (주문번호를 바꿔 남의 주문이 연결돼도 승인되지 않게)
        raise AppError(409, "문의 이메일과 주문자 이메일이 달라 승인할 수 없습니다. 본인 확인 후 진행하거나 반려해 주세요.",
                       "NOT_OWNER")
    if body.status == "승인" and ticket.ticket_type == "교환" and order is not None:
        # 교환: 배송 완료 + 불량·오배송 기한(30일) 안 (단순 변심 7일은 상담원이 사유를 보고 판단)
        if order.order_status != "배송 완료" or not order.delivered_at:
            raise AppError(409, f"주문이 '{order.order_status}' 상태라 교환을 승인할 수 없어요 (배송 완료 후에만).", "INVALID_STATE")
        if utcnow() > as_utc(order.delivered_at) + timedelta(days=DEFECT_RETURN_DAYS):
            raise AppError(409, f"배송 완료 후 {DEFECT_RETURN_DAYS}일이 지나 교환할 수 없어요. 반려하고 안내해 주세요.", "INVALID_STATE")
    order_change = None
    refund_note = None
    if body.status == "승인" and ticket.ticket_type == "취소":
        if order is None:
            raise AppError(409, "연결된 주문이 없어 취소할 수 없습니다. 주문번호를 확인해 주세요.", "INVALID_STATE")
        if order.order_status not in CANCELLABLE:
            raise AppError(409, f"이미 '{order.order_status}' 상태라 취소할 수 없습니다. 반려하고 반품으로 안내해 주세요.",
                           "INVALID_STATE")
        order_change = {"order_number": order.order_number, "before": order.order_status, "after": "취소"}
        order.order_status, order.shipping_status = "취소", None
        inventory.restock(db, order.product_name, order.quantity or 1)   # 취소한 수량은 재고로
        # 앞서 부분 취소 때 '3만원 미만'으로 뺀 배송비는, 주문을 모두 취소하면 출고되지 않았으니 돌려줌
        fee_back = SHIPPING_FEE * sum(1 for p in order.payments if p.kind == "승인 취소" and "배송비" in (p.memo or ""))
        # 결제 내역에 승인 취소 (카드는 3~5영업일 안에 반영, 주문 정보 카드의 '결제·환불 내역'에 보임)
        db.add(Payment(order_id=order.id, kind="승인 취소", method=order.payment_method, amount=order.amount + fee_back,
                       at=utcnow(), memo="주문 취소 (티켓 승인)"
                       + (f" · 부분 취소 때 뺀 배송비 {fee_back:,}원 함께 환불" if fee_back else "")))
    if body.status == "승인" and ticket.ticket_type in ("환불", "교환") and order is None:
        # 주문 연결이 끊긴 요청(주문번호를 없는 번호로 바꾼 경우 등): 환불 기록 없이 승인되지 않게 (취소와 같은 기준)
        raise AppError(409, "연결된 주문이 없어 승인할 수 없습니다. 주문번호를 확인해 주세요.", "INVALID_STATE")
    if body.status == "승인" and ticket.ticket_type == "환불" and order is not None:
        # 환불 예정 (실제 환불은 쇼핑몰 결제 시스템의 일. 상담원이 고객에게 예정일을 안내할 수 있게 기록)
        if order.order_status == "취소":
            raise AppError(409, "이미 취소된 주문이라 결제가 승인 취소로 처리됐어요. 환불 티켓은 반려해 주세요.", "INVALID_STATE")
        if any(p.kind == "환불" for p in order.payments):
            raise AppError(409, "이 주문에는 이미 환불(예정)이 있어요. 결제·환불 내역을 확인해 주세요.", "ALREADY_REFUNDED")
        if order.return_requested_at is None:
            # 반품 환불은 [반품 회수 접수] 뒤에: 거기서 배송 완료·반품 기한(7일/30일)을 확인하고 사유(배송비 차감 여부)를 남김
            raise AppError(409, "먼저 주문 정보의 [반품 회수 접수]를 해 주세요. 배송 완료·반품 기한을 확인하고 반품 사유를 남긴 뒤 환불을 승인해요.",
                           "RETURN_NOT_REQUESTED")
        reason = ctx.return_reason(db, order.order_number)   # [반품 회수 접수]에서 고른 사유
        waived = body.waive_return_fee and reason == "단순 변심"
        amount = order.amount if waived else ctx.refund_amount(order, reason)
        memo = "반품 회수·검수 후 3영업일 이내 (티켓 승인)"
        if waived:
            memo += " · 검수 결과 불량으로 배송비 차감 안 함 (전액)"
        elif amount < order.amount:   # 단순 변심: 안내한 대로 왕복 배송비 차감
            memo += f" · 단순 변심 왕복 배송비 {RETURN_FEE:,}원 차감"
        refund_note = {"amount": amount, "fee_waived": waived, "reason": reason}
        db.add(Payment(order_id=order.id, kind="환불", status="예정", method=order.payment_method, amount=amount,
                       at=sla.add_weekday_time(utcnow(), timedelta(days=REFUND_BUSINESS_DAYS)), memo=memo))   # 3영업일 (주말 제외)

    ticket.status, ticket.memo = body.status, body.memo
    ticket.handled_by, ticket.handled_at = user.id, utcnow()
    add_audit(db, request, "ticket_approve" if body.status == "승인" else "ticket_reject", user, "inquiry", inquiry.id,
              ticket_id=ticket.id, ticket_type=ticket.ticket_type, memo=body.memo, order=order_change, refund=refund_note)
    db.commit()
    return ticket


TICKET_STATUSES = ("접수", "승인", "반려")


@router.get("", summary="취소·교환·반품 요청(티켓) 목록 (로그인: 상담원은 내가 맡은 문의의 것만)")
def list_tickets(
    user: LoginUser, db: DB,
    status: str | None = Query("접수", description="접수(승인 대기) / 승인 / 반려 / all"),
    ticket_type: str | None = Query(None, description="취소 / 교환 / 환불"),
    page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=100),
):
    """AI가 접수한 취소·교환·반품 요청을 한곳에서 (승인·반려는 문의 상세에서, 주문 정보를 보고 판단)."""
    # 승인·반려하는 요청만 (AI의 '상담원 확인 요청'(이관)은 문의 목록에서 다루므로 여기 섞이지 않게, 대시보드 숫자와도 같게)
    stmt = (select(Ticket).join(Inquiry, Ticket.inquiry_id == Inquiry.id).where(Ticket.ticket_type.in_(ACTIONABLE))
            .options(selectinload(Ticket.inquiry).selectinload(Inquiry.assignee), selectinload(Ticket.order)))
    if user.role != "admin":
        stmt = stmt.where(Inquiry.assigned_to == user.id)
    if ticket_type:
        stmt = stmt.where(Ticket.ticket_type == ticket_type)
    # 상태별 건수 (위쪽 탭 숫자, 종류 조건은 같이 적용)
    counts = {s: db.scalar(select(func.count()).select_from(stmt.where(Ticket.status == s).subquery()))
              for s in TICKET_STATUSES}
    if status and status != "all":
        stmt = stmt.where(Ticket.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    # 승인 대기는 오래된 것부터(먼저 들어온 요청 먼저), 처리된 것은 최근 처리 순
    order = Ticket.created_at.asc() if status == "접수" else Ticket.handled_at.desc().nulls_last()
    rows = db.scalars(stmt.order_by(order, Ticket.id.desc()).offset((page - 1) * size).limit(size)).all()
    names = {u.id: u.display_name for u in db.scalars(select(AdminUser))}
    return {
        "items": [{
            "id": t.id, "ticket_type": t.ticket_type, "status": t.status, "reason": t.reason, "memo": t.memo,
            "created_at": as_utc(t.created_at), "handled_at": as_utc(t.handled_at),
            "handled_by": names.get(t.handled_by) if t.handled_by else None,
            "inquiry": {"id": t.inquiry.id, "inquiry_number": t.inquiry.inquiry_number, "title": t.inquiry.title,
                        "customer_name": t.inquiry.customer_name, "status": t.inquiry.status,
                        "assigned_to": t.inquiry.assignee.display_name if t.inquiry.assignee else None},
            "order": ({"order_number": t.order.order_number, "product_name": t.order.product_name, "amount": t.order.amount,
                       "order_status": t.order.order_status, "shipping_status": t.order.shipping_status}
                      if t.order else None),
        } for t in rows],
        "total": total, "counts": counts, "page": page, "size": size,
    }


REFUND_KINDS = ("환불", "승인 취소")   # 고객에게 돈이 돌아가는 결제 줄 (반품 환불 / 출고 전 취소의 카드 승인 취소)


@router.get("/refunds", summary="환불 진행 (승인 뒤 돈이 돌아가는 상황, 로그인: 상담원은 내가 맡은 문의의 주문만)")
def list_refunds(
    user: LoginUser, db: DB,
    state: str | None = Query("예정", description="예정 / 완료 / all"),
    page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=100),
):
    """취소·반품 요청을 승인한 뒤의 단계: 결제 내역의 '환불'·'승인 취소' 줄을 모아 봄 (조회 전용).
    실제 환불은 쇼핑몰 결제 시스템이 하므로, 예정일이 지났는데 '예정'이면 결제 시스템 확인이 필요하다는 표시(overdue)."""
    where = [Payment.kind.in_(REFUND_KINDS)]
    if user.role != "admin":
        mine = select(Inquiry.order_number).where(Inquiry.assigned_to == user.id, Inquiry.order_number.is_not(None))
        where.append(Order.order_number.in_(mine))
    now = utcnow()

    def agg(*cond, col=None):   # 건수 또는 금액 합계 (위쪽 요약)
        q = select(func.count() if col is None else func.coalesce(func.sum(col), 0))
        return db.scalar(q.select_from(Payment).join(Order, Payment.order_id == Order.id).where(*where, *cond)) or 0

    summary = {"pending": agg(Payment.status == "예정"), "pending_amount": agg(Payment.status == "예정", col=Payment.amount),
               "overdue": agg(Payment.status == "예정", Payment.at < now), "done": agg(Payment.status == "완료")}
    stmt = select(Payment, Order).join(Order, Payment.order_id == Order.id).where(*where)
    if state and state != "all":
        stmt = stmt.where(Payment.status == state)
    total = agg(*([Payment.status == state] if state and state != "all" else []))
    # 예정은 예정일 가까운 것부터, 완료는 최근 것부터
    sort = Payment.at.asc() if state == "예정" else Payment.at.desc()
    rows = db.execute(stmt.order_by(sort, Payment.id).offset((page - 1) * size).limit(size)).all()
    # 주문번호 → 그 주문의 가장 최근 문의 (줄을 누르면 문의 상세로)
    numbers = {o.order_number for _, o in rows}
    inquiries: dict[str, Inquiry] = {}
    if numbers:
        for i in db.scalars(select(Inquiry).where(Inquiry.order_number.in_(numbers)).order_by(Inquiry.id)):
            if user.role == "admin" or i.assigned_to == user.id:
                inquiries[i.order_number] = i
    return {
        "items": [{
            "id": p.id, "kind": p.kind, "status": p.status, "amount": p.amount, "method": p.method,
            "at": as_utc(p.at), "memo": p.memo, "overdue": p.status == "예정" and as_utc(p.at) < now,
            "order": {"order_number": o.order_number, "product_name": o.product_name, "amount": o.amount,
                      "order_status": o.order_status},
            "customer_name": o.customer.name if o.customer else None,
            "inquiry": ({"id": i.id, "inquiry_number": i.inquiry_number} if (i := inquiries.get(o.order_number)) else None),
        } for p, o in rows],
        "total": total, "summary": summary, "page": page, "size": size,
    }
