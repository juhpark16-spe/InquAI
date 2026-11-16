"""고객 문의 API 요청·응답 형식 (docs/api_spec.md 3장)."""

from pydantic import BaseModel, Field, field_validator

from backend.schemas.common import UTCDateTime

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
LOOKUP_PASSWORD_MIN = 6


def _clean_email(v: str) -> str:
    return v.strip().lower()


class InquiryCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=50)
    customer_email: str = Field(max_length=255, pattern=EMAIL_PATTERN)
    order_number: str | None = Field(default=None, max_length=30)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=5, max_length=2000)
    # 문의 조회용 비밀번호 (이메일과 함께 입력해 내 문의를 봄). 6자 이상: 4자리 숫자는 너무 쉽게 맞힐 수 있음
    password: str = Field(min_length=LOOKUP_PASSWORD_MIN, max_length=64)

    @field_validator("customer_email", mode="before")
    @classmethod
    def _email(cls, v):
        return _clean_email(v) if isinstance(v, str) else v

    @field_validator("customer_name", "title", "content", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("order_number", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v


class InquiryCreated(BaseModel):
    inquiry_number: str
    status: str
    answer: str | None
    message: str


class InquiryLookup(BaseModel):
    customer_email: str = Field(max_length=255)
    password: str = Field(min_length=1, max_length=64)

    @field_validator("customer_email", mode="before")
    @classmethod
    def _email(cls, v):
        return _clean_email(v) if isinstance(v, str) else v


class InquiryPublic(BaseModel):
    inquiry_number: str
    title: str
    content: str
    status: str
    answer: str | None
    created_at: UTCDateTime
    answered_at: UTCDateTime | None


class InquiryLookupResult(BaseModel):
    items: list[InquiryPublic]  # 최신순
