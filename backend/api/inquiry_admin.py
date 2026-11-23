"""문의 관리 API (로그인): 목록, 상세 (docs/api_spec.md 4장).

권한: 관리자는 모든 문의, 상담원은 자신에게 배정된 문의만 봅니다.
"""

from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.core.dependencies import DB, AdminOnly, LoginUser
from backend.core.errors import AppError
from backend.database.models import (DECISIONS, INQUIRY_STATUSES, URGENCIES, AdminUser, AnalysisResult, Attachment,
                                     Inquiry, InquiryNote, LabelCorrection, Notification, Order, utcnow)
from backend.schemas.inquiry import normalize_order_number
from backend.schemas.inquiry_admin import (AnalysisCorrection, AnalysisOut, AssignRequest, InquiryDetail, InquiryListItem, InquiryState, NoteCreate,
                                           NoteOut, Page, StatusRequest)
from backend.services import inquiry_context as ctx
from backend.services import recheck as recheck_svc
from backend.services import sla, uploads
from backend.services.audit import add_audit
from backend.services.corrections import apply_correction
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
    overdue: bool | None = Query(None, description="true 면 답변 기한(주말 제외, 긴급 4시간, 그 외 24시간)을 넘긴 미처리만"),
    assigned_to: str | None = Query(None, description="상담원 id, me, none (관리자만 지정 가능)"),
    recheck: bool | None = Query(None, description="true 면 '확인 후 다시 안내' 표시가 남은 문의만 (다시 안내 기한이 가까운 순)"),
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
    if open or overdue:
        stmt = stmt.where(Inquiry.status.in_(sla.OPEN_STATUSES))
    if overdue:
        # 기한은 주말을 빼고 계산해서 DB 조건으로 쓸 수 없음 → 미처리 문의(많지 않음)의 기한을 계산해 번호로 거름
        now = utcnow()
        rows = db.execute(select(Inquiry.id, func.coalesce(Inquiry.sla_started_at, Inquiry.created_at), AnalysisResult.urgency)
                          .outerjoin(AnalysisResult, AnalysisResult.inquiry_id == Inquiry.id)
                          .where(Inquiry.status.in_(sla.OPEN_STATUSES))).all()
        stmt = stmt.where(Inquiry.id.in_([i for i, created, urgency in rows if now > sla.due_at(created, urgency)]))
    if recheck:
        stmt = stmt.where(Inquiry.recheck_note.is_not(None))
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
    if recheck:
        order = [Inquiry.recheck_due_at]
    rows = db.execute(stmt.options(selectinload(Inquiry.assignee), selectinload(Inquiry.notes))
                      .order_by(*order, Inquiry.id.desc())
                      .offset((page - 1) * size).limit(size)).all()

    items = [{
        "id": i.id, "inquiry_number": i.inquiry_number, "title": i.title, "customer_name": i.customer_name,
        "status": i.status, "category": a.category if a else None, "urgency": a.urgency if a else None,
        "sentiment": a.sentiment if a else None, "decision": a.decision if a else None,
        "confidence": a.confidence if a else None,
        "assigned_to": _assignee(i.assignee), "created_at": i.created_at,
        "due_at": sla.due_at(sla.started(i), a.urgency if a else None),
        "overdue": sla.is_overdue(i.status, sla.started(i), a.urgency if a else None),
        "recheck_note": i.recheck_note, "recheck_due_at": i.recheck_due_at,
        "note_count": len(i.notes),   # 상담원 공유 메모 개수 (목록 제목 옆 📝)
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
    if before in ("완료", "자동 처리") and body.status in sla.OPEN_STATUSES:
        inquiry.sla_started_at = utcnow()   # 다시 열기: 답변 기한을 지금부터 다시 셈
    add_audit(db, request, "status_change", user, "inquiry", inquiry.id, before=before, after=body.status)
    db.commit()
    db.refresh(inquiry)
    return _state(inquiry)


@router.patch("/{inquiry_id}/analysis", response_model=AnalysisOut, summary="분류 결과 수정 (로그인, 재학습 데이터)")
def correct_analysis(inquiry_id: int, body: AnalysisCorrection, request: Request, user: LoginUser, db: DB):
    """AI가 잘못 고른 유형·감정을 고칩니다. 바뀐 항목마다 label_corrections에 원문과 함께 남겨 재학습에 씁니다.

    유형·감정이 바뀌면 처리 경로와 긴급도(답변 기한)를 규칙으로 다시 계산합니다. 에이전트는 다시 실행하지 않습니다.
    """
    inquiry = get_inquiry_for_user(db, inquiry_id, user)
    a = inquiry.analysis
    if a is None:
        raise AppError(400, "AI 분석이 없는 문의는 고칠 분류가 없습니다.", "NO_ANALYSIS")
    done = apply_correction(db, inquiry, user, category=body.category, sentiment=body.sentiment,
                            ip=request.client.host if request.client else None)
    if not done["changes"]:
        raise AppError(400, "지금과 같은 분류입니다.", "NO_CHANGE")
    db.commit()
    db.refresh(a)
    return a


@router.get("/{inquiry_id}/queue", summary="처리 대기열에서 이전·다음 문의 (로그인)")
def queue(inquiry_id: int, user: LoginUser, db: DB):
    """상세 화면의 [이전]·[다음]과 '처리 후 다음 미처리 문의로'에 씀.

    대기열 = 미처리 문의(접수·검토 대기·담당자 처리), 긴급도 높은 순 → 오래된 순 (먼저 온 문의부터).
    상담원은 자신에게 배정된 문의만. 지금 문의가 대기열에 없으면(완료 등) next 는 대기열의 첫 문의.
    """
    get_inquiry_for_user(db, inquiry_id, user)
    stmt = (select(Inquiry.id).outerjoin(AnalysisResult, AnalysisResult.inquiry_id == Inquiry.id)
            .where(Inquiry.status.in_(sla.OPEN_STATUSES)))
    if user.role != "admin":
        stmt = stmt.where(Inquiry.assigned_to == user.id)
    ids = list(db.scalars(stmt.order_by(URGENCY_ORDER, Inquiry.created_at, Inquiry.id)))
    if inquiry_id in ids:
        k = ids.index(inquiry_id)
        return {"total": len(ids), "position": k + 1, "prev_id": ids[k - 1] if k > 0 else None,
                "next_id": ids[k + 1] if k + 1 < len(ids) else None}
    return {"total": len(ids), "position": None, "prev_id": None, "next_id": ids[0] if ids else None}


@router.get("/{inquiry_id}", response_model=InquiryDetail, summary="문의 상세 (로그인)")
def get_inquiry(inquiry_id: int, user: LoginUser, db: DB):
    inquiry = get_inquiry_for_user(db, inquiry_id, user)
    corrections = db.scalars(select(LabelCorrection).where(LabelCorrection.inquiry_id == inquiry.id)
                             .order_by(LabelCorrection.id)).all()
    urgency = inquiry.analysis.urgency if inquiry.analysis else None
    names = {u.id: u.display_name for u in db.scalars(select(AdminUser))}
    return {
        "id": inquiry.id, "inquiry_number": inquiry.inquiry_number,
        "customer": {"name": inquiry.customer_name, "email": inquiry.customer_email,
                     "order_number": inquiry.order_number},
        "title": inquiry.title, "content": inquiry.content, "status": inquiry.status,
        "assigned_to": _assignee(inquiry.assignee), "created_at": inquiry.created_at,
        "updated_at": inquiry.updated_at, "analysis": inquiry.analysis, "responses": inquiry.responses,
        "tickets": sorted(inquiry.tickets, key=lambda t: t.id), "agent_logs": inquiry.agent_logs,
        "corrections": corrections,
        # 한 화면에서 판단·처리할 수 있도록 함께 보내는 업무 정보
        "order": ctx.order_card(db, inquiry),
        "email_orders": ctx.email_orders(db, inquiry),
        "order_hints": ctx.order_hints(db, inquiry),   # 고객 글에 적힌 다른 주문번호 ([이 번호로 확인])
        "customer_history": ctx.customer_history(db, inquiry, user),
        "customer_profile": ctx.customer_profile(db, inquiry),
        "faq_titles": ctx.faq_titles(db, inquiry),
        "history": ctx.history(db, inquiry),
        "due_at": sla.due_at(sla.started(inquiry), urgency),
        "overdue": sla.is_overdue(inquiry.status, sla.started(inquiry), urgency),
        "recheck": recheck_svc.info(inquiry, names),
        "photo_request": inquiry.photo_request,
        "messages": [{"id": m.id, "text": m.content, "created_at": m.created_at} for m in inquiry.messages],
        "notes": [{"id": n.id, "author": names.get(n.author_id, "?"), "author_id": n.author_id, "text": n.text,
                   "created_at": n.created_at}
                  for n in inquiry.notes],
        "attachments": inquiry.attachments,
        "notifications": db.scalars(select(Notification).where(Notification.inquiry_id == inquiry.id)
                                    .order_by(Notification.id)).all(),
    }


class OrderNumberBody(BaseModel):
    order_number: str | None = Field(default=None, max_length=30)   # 빈칸·null 이면 주문번호를 뗌

    @field_validator("order_number", mode="before")
    @classmethod
    def _order_number(cls, v):
        return normalize_order_number(v) if isinstance(v, str) else v


@router.patch("/{inquiry_id}/order-number", summary="주문번호 입력·변경 (로그인)")
def set_order_number(inquiry_id: int, body: OrderNumberBody, request: Request, user: LoginUser, db: DB):
    """고객이 주문번호를 빠뜨렸거나 잘못 적었을 때 상담원이 확인한 번호로 고침 (추가 문의·전화로 받은 번호, 이메일로 찾은 주문).
    없는 주문이면 409 (오타 방지). 문의 이메일과 주문자가 달라도 지정은 되지만 화면에 '본인 확인 필요'가 그대로 보임"""
    inquiry = get_inquiry_for_user(db, inquiry_id, user)
    new = body.order_number
    if new and db.scalar(select(Order.id).where(Order.order_number == new)) is None:
        raise AppError(409, f"주문번호 {new}에 해당하는 주문이 없습니다. 번호를 다시 확인해 주세요.", "ORDER_NOT_FOUND")
    before = inquiry.order_number
    if new != before:
        inquiry.order_number = new
        ctx.relink_open_tickets(db, inquiry)   # 처리 전 티켓도 새 주문으로
        add_audit(db, request, "order_number_change", user, "inquiry", inquiry.id, before=before, after=new)
        db.commit()
    return {"order_number": inquiry.order_number}


@router.post("/{inquiry_id}/notes", response_model=NoteOut, status_code=201, summary="상담원 공유 메모 남기기 (로그인)")
def add_note(inquiry_id: int, body: NoteCreate, request: Request, user: LoginUser, db: DB):
    """고객에게는 보이지 않는 상담원끼리의 메모 (인계 사항, 확인 중인 내용 등)"""
    inquiry = get_inquiry_for_user(db, inquiry_id, user)
    note = InquiryNote(inquiry_id=inquiry.id, author_id=user.id, text=body.text.strip())
    db.add(note)
    db.flush()
    add_audit(db, request, "note_create", user, "inquiry", inquiry.id, note_id=note.id)
    db.commit()
    return {"id": note.id, "author": user.display_name, "author_id": user.id, "text": note.text, "created_at": note.created_at}


@router.get("/{inquiry_id}/attachments/{attachment_id}", summary="첨부 사진 보기 (로그인)")
def get_attachment(inquiry_id: int, attachment_id: int, user: LoginUser, db: DB):
    inquiry = get_inquiry_for_user(db, inquiry_id, user)  # 상담원은 배정된 문의의 사진만
    att = db.get(Attachment, attachment_id)
    if att is None or att.inquiry_id != inquiry.id or not uploads.file_path(att).exists():
        raise AppError(404, "사진을 찾을 수 없습니다.", "NOT_FOUND")
    # 저장할 때 검사한 형식으로만 보내고, 브라우저가 다른 형식으로 해석하지 않게 함
    return FileResponse(uploads.file_path(att), media_type=att.content_type,
                        headers={"Content-Disposition": "inline", "Cache-Control": "private, max-age=300",
                                 "X-Content-Type-Options": "nosniff"})
