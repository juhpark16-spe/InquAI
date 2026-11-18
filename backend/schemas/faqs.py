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
