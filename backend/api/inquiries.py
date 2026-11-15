"""고객 API (공개): 문의 등록, 본인 문의 조회 (docs/api_spec.md 3장)."""

from fastapi import APIRouter, Depends, Request

from backend.core.config import get_settings
from backend.core.dependencies import DB
from backend.core.errors import AppError
from backend.core.rate_limit import rate_limit
from backend.schemas.inquiry import InquiryCreate, InquiryCreated, InquiryLookup, InquiryPublic
from backend.services.inquiries import find_public_inquiry, register_inquiry

router = APIRouter(prefix="/inquiries", tags=["고객 문의"])


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


@router.post("/lookup", response_model=InquiryPublic, summary="본인 문의 조회 (문의 번호 + 이메일)",
             dependencies=[Depends(rate_limit("inquiry_lookup", 10, 60))])
def lookup_inquiry(body: InquiryLookup, db: DB):
    found = find_public_inquiry(db, body.inquiry_number.strip(), body.customer_email)
    if found is None:  # 번호가 틀려도 이메일이 틀려도 같은 응답 (다른 사람 문의가 있는지 알 수 없게)
        raise AppError(404, "문의를 찾을 수 없습니다. 문의 번호와 이메일을 확인해 주세요.", "NOT_FOUND")
    return found
