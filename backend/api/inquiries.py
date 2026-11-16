"""고객 API (공개): 문의 등록, 본인 문의 조회 (docs/api_spec.md 3장)."""

from fastapi import APIRouter, Depends, Request

from backend.core.config import get_settings
from backend.core.dependencies import DB
from backend.core.errors import AppError
from backend.core.rate_limit import FailureLock, rate_limit
from backend.schemas.inquiry import InquiryCreate, InquiryCreated, InquiryLookup, InquiryLookupResult
from backend.services.inquiries import find_public_inquiries, register_inquiry

router = APIRouter(prefix="/inquiries", tags=["고객 문의"])

# 같은 이메일로 15분 안에 5번 틀리면 15분 동안 조회를 막음 (비밀번호 맞히기 방지)
lookup_failures = FailureLock(limit=5, window_seconds=15 * 60)
NOT_FOUND = "일치하는 문의가 없습니다. 이메일과 문의할 때 정한 비밀번호를 확인해 주세요."


def get_ai(request: Request) -> dict:
    """서버 시작 때 준비한 분석기·FAQ 검색·LLM (backend/main.py). 테스트에서는 가짜로 바꿔 끼웁니다."""
    state = request.app.state
    if getattr(state, "analyzer", None) is None:
        raise AppError(503, "분류 모델이 준비되지 않았습니다.", "MODEL_NOT_READY")
    return {"analyzer": state.analyzer, "faq_search": state.faq_search, "llm": state.llm}


# def 로 두면 FastAPI가 별도 스레드에서 실행해, LLM을 기다리는 동안 다른 요청을 막지 않음
@router.post("", status_code=201, response_model=InquiryCreated, summary="문의 등록 → 분석 → 에이전트 처리",
             dependencies=[Depends(rate_limit("inquiry_create", 5, 60))])
def create_inquiry(body: InquiryCreate, db: DB, ai: dict = Depends(get_ai)):
    return register_inquiry(db, body, timeout=get_settings().agent_timeout_seconds, **ai)


@router.post("/lookup", response_model=InquiryLookupResult, summary="내 문의 조회 (이메일 + 조회 비밀번호)",
             dependencies=[Depends(rate_limit("inquiry_lookup", 10, 60))])
def lookup_inquiries(body: InquiryLookup, db: DB):
    if lookup_failures.is_locked(body.customer_email):
        raise AppError(429, "비밀번호를 여러 번 틀려 잠시 조회할 수 없습니다. 15분 후 다시 시도해 주세요.",
                       "TOO_MANY_REQUESTS")
    items = find_public_inquiries(db, body.customer_email, body.password)
    if not items:  # 이메일이 없어도 비밀번호가 틀려도 같은 응답 (이메일로 문의한 적이 있는지 알 수 없게)
        lookup_failures.fail(body.customer_email)
        raise AppError(404, NOT_FOUND, "NOT_FOUND")
    return {"items": items}
