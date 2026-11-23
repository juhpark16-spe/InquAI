"""고객 문의 API 요청·응답 형식 (docs/api_spec.md 3장)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.schemas.common import UTCDateTime

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
LOOKUP_PASSWORD_MIN = 6


def _clean_email(v: str) -> str:
    return v.strip().lower()


class _Email(BaseModel):
    @field_validator("customer_email", mode="before", check_fields=False)
    @classmethod
    def _email(cls, v):
        return _clean_email(v) if isinstance(v, str) else v


class InquiryCreate(_Email):
    customer_name: str = Field(min_length=1, max_length=50)
    customer_email: str = Field(max_length=255, pattern=EMAIL_PATTERN)
    order_number: str | None = Field(default=None, max_length=30)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=5, max_length=2000)
    # 문의 조회용 비밀번호 (이메일과 함께 입력해 내 문의를 봄). 6자 이상: 4자리 숫자는 너무 쉽게 맞힐 수 있음
    # 쇼핑몰에 로그인한 고객은 '내 문의'에서 바로 보므로 비워도 됨 (비회원은 필수, api/inquiries.py에서 확인)
    password: str | None = Field(default=None, min_length=LOOKUP_PASSWORD_MIN, max_length=64)
    # 개인정보 수집·이용 동의 (비회원 문의에 이름·이메일을 받으므로 필수)
    # validate_default: 항목을 아예 보내지 않아도(기본값 False) 아래 검사를 거치게 함
    privacy_agreed: bool = Field(default=False, validate_default=True)
    # 먼저 올린 사진의 token (POST /api/inquiries/uploads), 최대 3장
    attachment_tokens: list[str] = Field(default_factory=list, max_length=3)
    # 파손·불량·오배송 문의의 사진 칸 (token → '송장' / '파손 부위'), 고객이 고른 '파손·불량·오배송 문의예요',
    # '지금은 사진이 없어요' (backend/services/photo_evidence.py)
    photo_labels: dict[str, Literal["송장", "파손 부위"]] = Field(default_factory=dict, max_length=3)
    damage_report: bool = False
    photos_later: bool = False

    @field_validator("customer_name", "title", "content", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("order_number", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return (v.strip() or None) if isinstance(v, str) else v

    @field_validator("privacy_agreed")
    @classmethod
    def _must_agree(cls, v):
        if not v:
            raise ValueError("개인정보 수집·이용에 동의해야 문의를 등록할 수 있습니다.")
        return v


class InquiryCreated(BaseModel):
    inquiry_number: str
    status: str
    answer: str | None
    message: str


class InquiryLookup(_Email):
    customer_email: str = Field(max_length=255)
    password: str = Field(min_length=1, max_length=64)


class FollowUpCreate(InquiryLookup):
    """추가 문의: 본인 확인(이메일 + 비밀번호) + 어느 문의에 이어서 쓰는지"""
    inquiry_number: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=2, max_length=2000)
    attachment_tokens: list[str] = Field(default_factory=list, max_length=3)

    @field_validator("content", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v


class RatingCreate(InquiryLookup):
    helpful: bool


class UploadOut(BaseModel):
    token: str
    filename: str
    size: int


class PublicAnswer(BaseModel):
    id: int
    text: str
    answered_at: UTCDateTime
    by: str  # "AI 상담원" 또는 "상담원"
    rating: int | None  # 1 도움됨, -1 도움 안 됨


class PublicMessage(BaseModel):
    id: int
    text: str
    at: UTCDateTime


class PublicAttachment(BaseModel):
    url: str               # 30분짜리 서명 주소
    filename: str
    message_id: int | None  # 추가 문의에 붙은 사진이면 그 메시지 id
    label: str | None = None  # 파손 문의의 사진 칸: 송장 / 파손 부위


class InquiryPublic(BaseModel):
    inquiry_number: str
    title: str
    content: str
    status: str
    answer: str | None
    created_at: UTCDateTime
    answered_at: UTCDateTime | None
    answers: list[PublicAnswer]    # 보낸 답변 전부 (시간순), answer 는 그중 마지막
    messages: list[PublicMessage]  # 고객의 추가 문의 (시간순)
    attachment_count: int
    attachments: list[PublicAttachment]
    can_follow_up: bool            # 추가 문의를 남길 수 있는지
    more_answer_coming: bool = False  # 상담원이 확인 후 다시 안내하기로 함 → '추가 안내 예정'


class InquiryLookupResult(BaseModel):
    items: list[InquiryPublic]  # 최신순
    notice: str                 # 답변 시간 안내
