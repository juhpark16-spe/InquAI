"""고객 API (공개): 문의 등록, 사진 올리기, 내 문의 조회, 추가 문의, 답변 평가 (docs/api_spec.md 3장)."""

from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse

from backend.core.config import get_settings
from backend.core.dependencies import DB, MaybeCustomer
from backend.core.errors import AppError
from backend.core.rate_limit import FailureLock, rate_limit
from backend.database.models import Attachment
from backend.schemas.inquiry import (FollowUpCreate, InquiryCreate, InquiryCreated, InquiryLookup, InquiryLookupResult,
                                     RatingCreate, UploadOut)
from backend.services.drafts import write_draft
from backend.services import sla, uploads
from backend.services.inquiries import (add_follow_up, find_owned_inquiry, find_public_inquiries, rate_answer,
                                        register_inquiry)

router = APIRouter(prefix="/inquiries", tags=["고객 문의"])

# 같은 이메일로 15분 안에 5번 틀리면 15분 동안 조회를 막음 (비밀번호 맞히기 방지). 추가 문의·평가도 같은 잠금을 씀
lookup_failures = FailureLock(limit=5, window_seconds=15 * 60)
NOT_FOUND = "일치하는 문의가 없습니다. 이메일과 문의할 때 정한 비밀번호를 확인해 주세요."
LOCKED = "비밀번호를 여러 번 틀려 잠시 조회할 수 없습니다. 15분 후 다시 시도해 주세요."


def get_ai(request: Request) -> dict:
    """서버 시작 때 준비한 분석기·FAQ 검색·LLM (backend/main.py). 테스트에서는 가짜로 바꿔 끼웁니다."""
    state = request.app.state
    if getattr(state, "analyzer", None) is None:
        raise AppError(503, "분류 모델이 준비되지 않았습니다.", "MODEL_NOT_READY")
    return {"analyzer": state.analyzer, "faq_search": state.faq_search, "llm": state.llm}


def _check_lock(email: str) -> None:
    if lookup_failures.is_locked(email):
        raise AppError(429, LOCKED, "TOO_MANY_REQUESTS")


def _owned_or_404(db, body: FollowUpCreate | RatingCreate, inquiry_number: str):
    _check_lock(body.customer_email)
    inquiry = find_owned_inquiry(db, body.customer_email, body.password, inquiry_number)
    if inquiry is None:
        lookup_failures.fail(body.customer_email)
        raise AppError(404, NOT_FOUND, "NOT_FOUND")
    return inquiry


@router.post("/uploads", response_model=UploadOut, status_code=201, summary="사진 올리기 (문의 등록 전, 공개)",
             dependencies=[Depends(rate_limit("upload", 10, 60))])
async def upload_photo(db: DB, file: UploadFile = File(...)):
    data = await file.read(uploads.MAX_BYTES + 1)  # 제한보다 1바이트 더 읽어 초과 여부만 확인
    att = uploads.save_upload(db, file.filename or "photo", data)
    return {"token": att.token, "filename": att.filename, "size": att.size}


# def 로 두면 FastAPI가 별도 스레드에서 실행해, LLM을 기다리는 동안 다른 요청을 막지 않음
@router.post("", status_code=201, response_model=InquiryCreated, summary="문의 등록 → 분석 → 에이전트 처리",
             dependencies=[Depends(rate_limit("inquiry_create", 5, 60))])
def create_inquiry(body: InquiryCreate, db: DB, background: BackgroundTasks, customer: MaybeCustomer,
                   ai: dict = Depends(get_ai)):
    if customer is not None:
        # 쇼핑몰 로그인 고객: 이름·이메일은 계정 정보로 (화면 값보다 우선), 주문번호는 본인 주문만
        body.customer_name, body.customer_email = customer.name, customer.email
        if body.order_number and not any(o.order_number == body.order_number for o in customer.orders):
            raise AppError(422, "내 주문 목록에 없는 주문번호입니다.", "ORDER_NOT_FOUND")
    elif not body.password:
        raise AppError(422, "문의 조회 비밀번호를 입력해 주세요.", "VALIDATION_ERROR")
    timeout = get_settings().agent_timeout_seconds
    # 답변 초안은 고객에게 응답한 뒤에 씀 (고객이 기다리지 않게, backend/services/drafts.py)
    schedule = lambda inquiry_id: background.add_task(  # noqa: E731
        write_draft, inquiry_id, ai["faq_search"], ai["llm"], timeout)
    return register_inquiry(db, body, timeout=timeout, schedule_draft=schedule, **ai)


@router.post("/lookup", response_model=InquiryLookupResult, summary="내 문의 조회 (이메일 + 조회 비밀번호)",
             dependencies=[Depends(rate_limit("inquiry_lookup", 10, 60))])
def lookup_inquiries(body: InquiryLookup, db: DB):
    _check_lock(body.customer_email)
    items = find_public_inquiries(db, body.customer_email, body.password)
    if not items:  # 이메일이 없어도 비밀번호가 틀려도 같은 응답 (이메일로 문의한 적이 있는지 알 수 없게)
        lookup_failures.fail(body.customer_email)
        raise AppError(404, NOT_FOUND, "NOT_FOUND")
    return {"items": items, "notice": sla.CUSTOMER_NOTICE}


@router.get("/attachments/{attachment_id}", summary="내 첨부 사진 보기 (조회 응답의 서명 주소, 30분)",
            dependencies=[Depends(rate_limit("attachment_view", 120, 60))])
def view_my_photo(attachment_id: int, exp: int, sig: str, db: DB):
    att = db.get(Attachment, attachment_id)
    if not uploads.verify_link(attachment_id, exp, sig) or att is None or att.inquiry_id is None \
            or not uploads.file_path(att).exists():
        raise AppError(404, "사진을 찾을 수 없거나 보기 시간이 지났습니다. 문의를 다시 조회해 주세요.", "NOT_FOUND")
    return FileResponse(uploads.file_path(att), media_type=att.content_type,
                        headers={"Content-Disposition": "inline", "Cache-Control": "private, max-age=600"})


@router.post("/follow-up", status_code=201, summary="추가 문의 (같은 문의에 이어서)",
             dependencies=[Depends(rate_limit("follow_up", 5, 60))])
def follow_up(body: FollowUpCreate, db: DB):
    inquiry = _owned_or_404(db, body, body.inquiry_number.strip())
    add_follow_up(db, inquiry, body.content, body.attachment_tokens, body.order_number)
    return {"inquiry_number": inquiry.inquiry_number, "status": inquiry.status,
            "message": "추가 문의가 접수되었습니다. " + sla.CUSTOMER_NOTICE}


@router.post("/answers/{response_id}/rating", summary="답변 평가 (도움이 되었나요?)",
             dependencies=[Depends(rate_limit("rating", 20, 60))])
def rate(response_id: int, inquiry_number: str, body: RatingCreate, db: DB):
    inquiry = _owned_or_404(db, body, inquiry_number.strip())
    r = rate_answer(db, inquiry, response_id, body.helpful)
    return {"id": r.id, "rating": r.rating}
