"""고객 문의 API 요청·응답 형식 (docs/api_spec.md 3장)."""

from pydantic import BaseModel, Field, field_validator

from backend.schemas.common import UTCDateTime

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


def _clean_email(v: str) -> str:
    return v.strip().lower()


class InquiryCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=50)
    customer_email: str = Field(max_length=255, pattern=EMAIL_PATTERN)
    order_number: str | None = Field(default=None, max_length=30)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=5, max_length=2000)

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
    inquiry_number: str = Field(min_length=1, max_length=20)
    customer_email: str = Field(max_length=255)

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
