"""FAQ 관리 API(관리자) 요청·응답 형식."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.schemas.common import UTCDateTime
from backend.training.labels import CATEGORY_LABELS

Category = Literal[tuple(CATEGORY_LABELS)]
CODE_PATTERN = r"^F\d{2,4}$"   # F01, F45 …


class FaqBody(BaseModel):
    category: Category
    question: str = Field(min_length=5, max_length=200)
    answer: str = Field(min_length=10, max_length=1000)

    @field_validator("question", "answer")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 5:
            raise ValueError("내용이 너무 짧습니다.")
        return v


class FaqCreate(FaqBody):
    code: str | None = Field(None, pattern=CODE_PATTERN, description="비우면 다음 번호를 자동으로 붙임")


class FaqUpdate(FaqBody):
    is_active: bool = True


class FaqAdmin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    category: str
    question: str
    answer: str
    is_active: bool
    created_at: UTCDateTime
    updated_at: UTCDateTime
    used_count: int = 0           # AI 자동 답변·초안의 근거로 쓰인 횟수 (agent_logs.used_faq_ids)
    last_used_at: UTCDateTime | None = None


class SearchHit(BaseModel):
    code: str
    category: str
    question: str
    score: float
    suggested: bool               # 고객 화면 추천 기준값 이상인지


class SearchTest(BaseModel):
    engine: str | None
    suggest_min_score: float | None
    hits: list[SearchHit]


class SuggestExample(BaseModel):
    inquiry_id: int
    inquiry_number: str
    title: str
    content: str


class NearestFaq(BaseModel):
    code: str
    question: str
    score: float


class FaqSuggestion(BaseModel):
    count: int                      # 묶인 문의 수
    category: str
    question: str
    answer: str                     # LLM 초안 (상담원 답변만 근거, 확인할 곳은 [확인 필요: …])
    check_points: list[str]
    drafted: bool                   # LLM 초안을 썼는지 (LLM이 없거나 실패하면 False → 질문만)
    with_staff_answer: int          # 상담원이 답변을 보낸 문의 수 (초안 근거)
    nearest_faq: NearestFaq | None  # 지금 가장 비슷한 FAQ (기준값 미만이라 추천 대상)
    examples: list[SuggestExample]


class FaqSuggestRequest(BaseModel):
    days: int = Field(30, ge=7, le=90)
    min_count: int = Field(2, ge=2, le=10)


class FaqSuggestResult(BaseModel):
    days: int
    candidates: int                 # 자동 답변하지 못했고 비슷한 FAQ도 없는 문의 수
    engine: str
    items: list[FaqSuggestion]
