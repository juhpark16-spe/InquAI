"""답변 API (로그인): 상담원 직접 작성, 초안 수정, 승인·발송 (docs/api_spec.md 5장).

    POST /api/inquiries/{id}/responses     상담원이 직접 작성 (send=true 면 바로 발송, false 면 초안 저장)
    PUT  /api/responses/{id}               초안 수정 (AI 초안이든 상담원 초안이든)
    POST /api/responses/{id}/approve       승인·발송 → 문의 상태 '완료'
    POST /api/inquiries/{id}/draft         AI 초안 만들기 (FAQ·주문 정보·대화를 근거로, 상담원이 검토 후 발송)

'발송'은 메일이 아니라 DB 저장입니다. 고객은 내 문의 조회(이메일 + 비밀번호)에서 답변을 봅니다.
권한은 문의와 같습니다: 관리자는 전체, 상담원은 자신에게 배정된 문의만.
"""

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.agents.drafting import generate_draft
from backend.api.inquiry_admin import get_inquiry_for_user
from backend.core.config import get_settings
from backend.core.dependencies import DB, LoginUser
from backend.core.errors import AppError
from backend.core.rate_limit import rate_limit
from backend.database.models import AdminUser, Inquiry, Response, utcnow
from backend.schemas.inquiry_admin import ResponseOut
from backend.services import notify
from backend.services.audit import add_audit

router = APIRouter(tags=["답변"])
logger = logging.getLogger("inquai")

MAX_LEN = 4000


class _Text(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_LEN)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v):
        if not v.strip():
            raise ValueError("답변 내용을 입력해 주세요.")
        return v.strip()


class ResponseCreate(_Text):
    send: bool = False  # true: 바로 발송, false: 초안으로 저장


class ResponseUpdate(_Text):
    pass


class DraftRequest(BaseModel):
    replace: bool = False  # 상담원이 고친 초안이 있어도 AI 초안으로 바꿀지


def _get_response_for_user(db: Session, response_id: int, user: AdminUser) -> Response:
    response = db.get(Response, response_id)
    if response is None:
        raise AppError(404, "답변을 찾을 수 없습니다.", "NOT_FOUND")
    get_inquiry_for_user(db, response.inquiry_id, user)  # 문의 권한 확인 (상담원은 배정된 문의만)
    return response


def _send(db: Session, request: Request, response: Response, user: AdminUser) -> None:
    final = response.final_text or response.draft_text
    response.final_text = final
    # AI 초안을 고쳐서 보냈는지 (성공 지표: 초안 무수정 승인율). 상담원이 직접 쓴 답변은 해당 없음
    response.is_edited = response.generated_by == "llm" and final != response.draft_text
    response.status = "발송"
    response.approved_by, response.approved_at = user.id, utcnow()
    inquiry = db.get(Inquiry, response.inquiry_id)
    before = inquiry.status
    inquiry.status = "완료"
    add_audit(db, request, "response_approve", user, "inquiry", inquiry.id, response_id=response.id,
              generated_by=response.generated_by, is_edited=response.is_edited, before=before, after="완료")
    notify.answer_registered(db, inquiry)  # 고객에게 "답변이 등록되었습니다" 알림 (시연용 기록)


@router.post("/inquiries/{inquiry_id}/responses", response_model=ResponseOut, status_code=201,
             summary="답변 직접 작성 (로그인)")
def create_response(inquiry_id: int, body: ResponseCreate, request: Request, user: LoginUser, db: DB):
    inquiry = get_inquiry_for_user(db, inquiry_id, user)
    pending = db.scalar(select(Response).where(Response.inquiry_id == inquiry.id, Response.status == "초안"))
    if pending is not None:  # 초안이 둘이면 무엇을 보낼지 헷갈리므로, 있는 초안을 고쳐 쓰게 함
        raise AppError(409, "보내지 않은 초안이 이미 있습니다. 그 초안을 수정해 주세요.", "DRAFT_EXISTS",
                       response_id=pending.id)
    response = Response(inquiry_id=inquiry.id, draft_text=body.text, final_text=body.text,
                        generated_by="agent_user", used_faq_ids=[], status="초안")
    db.add(response)
    db.flush()
    add_audit(db, request, "response_create", user, "inquiry", inquiry.id, response_id=response.id)
    if body.send:
        _send(db, request, response, user)
    db.commit()
    db.refresh(response)
    return response


@router.put("/responses/{response_id}", response_model=ResponseOut, summary="답변 초안 수정 (로그인)")
def update_response(response_id: int, body: ResponseUpdate, request: Request, user: LoginUser, db: DB):
    response = _get_response_for_user(db, response_id, user)
    if response.status != "초안":
        raise AppError(400, "이미 발송한 답변은 수정할 수 없습니다.", "INVALID_STATE")
    if body.text != (response.final_text or response.draft_text):
        response.final_text = body.text
        add_audit(db, request, "response_edit", user, "inquiry", response.inquiry_id, response_id=response.id)
    db.commit()
    db.refresh(response)
    return response


@router.post("/responses/{response_id}/approve", response_model=ResponseOut, summary="승인·발송 (로그인)")
def approve_response(response_id: int, request: Request, user: LoginUser, db: DB, body: ResponseUpdate | None = None):
    """body 로 최종 문장을 함께 보내면 그 내용으로 저장 후 발송 (수정과 발송을 한 번에)."""
    response = _get_response_for_user(db, response_id, user)
    if response.status != "초안":
        raise AppError(400, "이미 발송한 답변입니다.", "INVALID_STATE")
    if body is not None:
        response.final_text = body.text
    _send(db, request, response, user)
    db.commit()
    db.refresh(response)
    return response


@router.post("/inquiries/{inquiry_id}/draft", response_model=ResponseOut, summary="AI 답변 초안 만들기 (로그인)",
             dependencies=[Depends(rate_limit("draft_generate", 10, 60))])
def create_draft(inquiry_id: int, request: Request, user: LoginUser, db: DB, body: DraftRequest | None = None):
    """검색된 FAQ, 본인 확인된 주문 정보, 처리 기록, 대화를 근거로 초안을 씁니다. 보내지 않은 초안이 있으면 그 자리에 씀.

    상담원이 고친(또는 직접 쓴) 초안이 있으면 replace=true 일 때만 바꿉니다 (작성 중인 글을 실수로 지우지 않게).
    """
    replace = body.replace if body else False
    inquiry = get_inquiry_for_user(db, inquiry_id, user)
    llm = getattr(request.app.state, "llm", None)
    if llm is None:
        raise AppError(503, "AI를 쓸 수 없어 초안을 만들 수 없습니다. 직접 작성해 주세요.", "LLM_UNAVAILABLE")
    draft = db.scalar(select(Response).where(Response.inquiry_id == inquiry.id, Response.status == "초안"))
    edited = draft is not None and (draft.generated_by != "llm" or draft.final_text not in (None, draft.draft_text))
    if edited and not replace:
        raise AppError(409, "상담원이 고친 초안이 있습니다. AI 초안으로 바꾸려면 다시 확인해 주세요.", "DRAFT_EDITED",
                       response_id=draft.id)

    try:
        result = generate_draft(db, inquiry, getattr(request.app.state, "faq_search", None), llm,
                                timeout=get_settings().agent_timeout_seconds)
    except Exception:  # noqa: BLE001  LLM 오류·시간 초과
        logger.exception("AI 초안 생성 실패: %s", inquiry.inquiry_number)
        raise AppError(502, "AI 초안을 만들지 못했습니다. 잠시 후 다시 시도하거나 직접 작성해 주세요.", "DRAFT_FAILED")

    if draft is None:
        draft = Response(inquiry_id=inquiry.id, generated_by="llm", status="초안", draft_text=result.answer)
        db.add(draft)
    draft.draft_text, draft.final_text, draft.generated_by = result.answer, None, "llm"
    draft.used_faq_ids, draft.grounded, draft.check_points = result.used_faq_ids, result.grounded, result.check_points or None
    db.flush()
    add_audit(db, request, "draft_generate", user, "inquiry", inquiry.id, response_id=draft.id, replaced=edited,
              faqs=result.retrieved_faqs, tokens=result.tokens, latency_ms=result.latency_ms, llm_model=result.llm_model)
    db.commit()
    db.refresh(draft)
    return draft
