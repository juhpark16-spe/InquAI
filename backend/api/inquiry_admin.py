"""문의 관리 API (로그인): 목록, 상세 (docs/api_spec.md 4장).

권한: 관리자는 모든 문의, 상담원은 자신에게 배정된 문의만 봅니다.
"""

from typing import Literal

from fastapi import APIRouter, Query, Request
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.core.dependencies import DB, AdminOnly, LoginUser
from backend.core.errors import AppError
from backend.database.models import (DECISIONS, INQUIRY_STATUSES, URGENCIES, AdminUser, AnalysisResult, Inquiry,
                                     LabelCorrection)
from backend.schemas.inquiry_admin import (AssignRequest, InquiryDetail, InquiryListItem, InquiryState, Page,
                                           StatusRequest)
from backend.services.audit import add_audit
from backend.training.labels import CATEGORY_LABELS

router = APIRouter(prefix="/inquiries", tags=["문의 관리"])

URGENCY_ORDER = case({"높음": 0, "보통": 1, "낮음": 2}, value=AnalysisResult.urgency, else_=3)


def get_inquiry_for_user(db: Session, inquiry_id: int, user: AdminUser) -> Inquiry:
    """문의를 찾고 권한을 확인합니다. 배정·상태 변경 등 다른 관리 API도 이 함수를 씁니다."""
    inquiry = db.get(Inquiry, inquiry_id)
    if inquiry is None:
        raise AppError(404, "문의를 찾을 수 없습니다.", "NOT_FOUND")
    if user.role != "admin" and inquiry.assigned_to != user.id:
        raise AppError(403, "배정된 문의만 볼 수 있습니다.", "FORBIDDEN")
    return inquiry


def _assignee(user: AdminUser | None) -> dict | None:
    return {"id": user.id, "display_name": user.display_name} if user else None


@router.get("", response_model=Page[InquiryListItem], summary="문의 목록 (로그인)")
def list_inquiries(
    user: LoginUser,
    db: DB,
    category: Literal[tuple(CATEGORY_LABELS)] | None = None,
    urgency: Literal[URGENCIES] | None = None,
    status: Literal[INQUIRY_STATUSES] | None = None,
    decision: Literal[DECISIONS] | None = None,
    open: bool | None = Query(None, description="true 면 미처리(접수·검토 대기·담당자 처리)만"),
    assigned_to: str | None = Query(None, description="상담원 id, me, none (관리자만 지정 가능)"),
    q: str | None = Query(None, max_length=100, description="제목·내용·문의 번호·이메일 검색"),
    sort: Literal["urgency", "-created_at"] = "urgency",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    stmt = select(Inquiry, AnalysisResult).outerjoin(AnalysisResult, AnalysisResult.inquiry_id == Inquiry.id)

    if user.role != "admin":
        assigned_to = "me"  # 상담원은 자신에게 배정된 문의만
    if assigned_to == "me":
        stmt = stmt.where(Inquiry.assigned_to == user.id)
    elif assigned_to == "none":
        stmt = stmt.where(Inquiry.assigned_to.is_(None))
    elif assigned_to:
        if not assigned_to.isdigit():
            raise AppError(422, "assigned_to 는 상담원 id, me, none 중 하나입니다.", "INVALID_PARAM")
        stmt = stmt.where(Inquiry.assigned_to == int(assigned_to))

    if status:
        stmt = stmt.where(Inquiry.status == status)
    if open:
        stmt = stmt.where(Inquiry.status.in_(("접수", "검토 대기", "담당자 처리")))
    if category:
        stmt = stmt.where(AnalysisResult.category == category)
    if urgency:
        stmt = stmt.where(AnalysisResult.urgency == urgency)
    if decision:
        stmt = stmt.where(AnalysisResult.decision == decision)
    if q and q.strip():
        word = q.strip()
        stmt = stmt.where(or_(*(col.contains(word, autoescape=True) for col in (
            Inquiry.title, Inquiry.content, Inquiry.inquiry_number, Inquiry.customer_email))))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = [URGENCY_ORDER, Inquiry.created_at.desc()] if sort == "urgency" else [Inquiry.created_at.desc()]
    rows = db.execute(stmt.options(selectinload(Inquiry.assignee)).order_by(*order, Inquiry.id.desc())
                      .offset((page - 1) * size).limit(size)).all()

    items = [{
        "id": i.id, "inquiry_number": i.inquiry_number, "title": i.title, "customer_name": i.customer_name,
        "status": i.status, "category": a.category if a else None, "urgency": a.urgency if a else None,
        "sentiment": a.sentiment if a else None, "decision": a.decision if a else None,
        "assigned_to": _assignee(i.assignee), "created_at": i.created_at,
    } for i, a in rows]
    return {"items": items, "total": total, "page": page, "size": size}


def _state(inquiry: Inquiry) -> dict:
    return {"id": inquiry.id, "inquiry_number": inquiry.inquiry_number, "status": inquiry.status,
            "assigned_to": _assignee(inquiry.assignee), "updated_at": inquiry.updated_at}


@router.patch("/{inquiry_id}/assign", response_model=InquiryState, summary="배정·재배정 (관리자)")
def assign_inquiry(inquiry_id: int, body: AssignRequest, request: Request, admin: AdminOnly, db: DB):
    inquiry = get_inquiry_for_user(db, inquiry_id, admin)
    if body.assigned_to is not None:
        target = db.get(AdminUser, body.assigned_to)
        if target is None or not target.is_active:
            raise AppError(400, "배정할 수 없는 계정입니다.", "INVALID_ASSIGNEE")

    before = {"assigned_to": inquiry.assigned_to, "status": inquiry.status}
    inquiry.assigned_to = body.assigned_to
    # 사람이 맡았으므로 '접수'·'검토 대기'는 '담당자 처리'로. 완료·자동 처리된 문의는 상태를 그대로 둠
    if body.assigned_to is not None and inquiry.status in ("접수", "검토 대기"):
        inquiry.status = "담당자 처리"
    after = {"assigned_to": inquiry.assigned_to, "status": inquiry.status}
    if before != after:
        add_audit(db, request, "assign", admin, "inquiry", inquiry.id, before=before, after=after)
    db.commit()
    db.refresh(inquiry)
    return _state(inquiry)


@router.patch("/{inquiry_id}/status", response_model=InquiryState, summary="상태 변경 (로그인)")
def change_status(inquiry_id: int, body: StatusRequest, request: Request, user: LoginUser, db: DB):
    """답변 없이 끝내는 문의(중복·스팸 등)를 완료로 바꾸거나, 완료한 문의를 다시 여는 데 씁니다."""
    inquiry = get_inquiry_for_user(db, inquiry_id, user)
    if inquiry.status == body.status:
        raise AppError(400, f"이미 '{body.status}' 상태입니다.", "INVALID_STATE")
    before = inquiry.status
    inquiry.status = body.status
    add_audit(db, request, "status_change", user, "inquiry", inquiry.id, before=before, after=body.status)
    db.commit()
    db.refresh(inquiry)
    return _state(inquiry)


@router.get("/{inquiry_id}", response_model=InquiryDetail, summary="문의 상세 (로그인)")
def get_inquiry(inquiry_id: int, user: LoginUser, db: DB):
    inquiry = get_inquiry_for_user(db, inquiry_id, user)
    corrections = db.scalars(select(LabelCorrection).where(LabelCorrection.inquiry_id == inquiry.id)
                             .order_by(LabelCorrection.id)).all()
    return {
        "id": inquiry.id, "inquiry_number": inquiry.inquiry_number,
        "customer": {"name": inquiry.customer_name, "email": inquiry.customer_email,
                     "order_number": inquiry.order_number},
        "title": inquiry.title, "content": inquiry.content, "status": inquiry.status,
        "assigned_to": _assignee(inquiry.assignee), "created_at": inquiry.created_at,
        "updated_at": inquiry.updated_at, "analysis": inquiry.analysis, "responses": inquiry.responses,
        "tickets": sorted(inquiry.tickets, key=lambda t: t.id), "agent_logs": inquiry.agent_logs,
        "corrections": corrections,
    }
