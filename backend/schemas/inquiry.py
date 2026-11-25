"""고객 문의 API 요청·응답 형식 (docs/api_spec.md 3장)."""

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.schemas.common import UTCDateTime

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# 쇼핑몰 주문번호: 주문일 8자리 - 그날 순번 4자리 (예: 20261103-0042). 하이픈 없이 12자리로 적어도 받아 줌
ORDER_NUMBER = re.compile(r"^\d{8}-\d{4}$")
ORDER_NUMBER_HELP = "주문번호는 20261103-0042처럼 숫자 8자리-4자리예요. 마이페이지 > 주문내역에서 확인해 주세요."


def normalize_order_number(v: str | None) -> str | None:
    """빈칸 → None, 공백 제거, 12자리 숫자 → 8-4 (예: 202611030042 → 20261103-0042). 형식이 다르면 ValueError"""
    if v is None:
        return None
    v = re.sub(r"\s", "", v)
    if not v:
        return None
    if re.fullmatch(r"\d{12}", v):
        v = f"{v[:8]}-{v[8:]}"
    if not ORDER_NUMBER.match(v):
        raise ValueError(ORDER_NUMBER_HELP)
    return v


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
    damage_report: bool | None = None
    client_request_id: str | None = Field(default=None, max_length=64)   # 화면이 만든 값: 같은 값이면 같은 문의   # 파손 체크: None = 내용으로 판단, true/false = 고객이 고른 그대로
    photos_later: bool = False

    @field_validator("customer_name", "title", "content", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("order_number", mode="before")
    @classmethod
    def _order_number(cls, v):
        return normalize_order_number(v) if isinstance(v, str) else v

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
    content: str = Field(default="", max_length=2000)   # 사진·주문번호만 보낼 때는 비워도 됨 (fill_follow_up)
    attachment_tokens: list[str] = Field(default_factory=list, max_length=3)
    # 처음 문의에 주문번호가 없을 때만 받음 (있으면 무시). 형식은 문의 등록과 같음
    order_number: str | None = Field(default=None, max_length=30)

    @field_validator("order_number", mode="before")
    @classmethod
    def _order_number(cls, v):
        return normalize_order_number(v) if isinstance(v, str) else v

    @field_validator("content", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _fill(self):
        return fill_follow_up(self)


def fill_follow_up(body):
    """추가 문의는 글 2자 이상, 또는 사진·주문번호만 보내도 됨 (파손 사진을 나중에 보낼 때).
    글이 짧으면 무엇을 보냈는지 대화에 남도록 채움 (쇼핑몰 로그인 추가 문의 api/shop.py FollowUpBody 도 같이 씀)"""
    if len(body.content) >= 2:
        return body
    sent = [x for x, ok in (("사진", body.attachment_tokens), ("주문번호", body.order_number)) if ok]
    if not sent:
        raise ValueError("내용을 2자 이상 적거나 사진을 올려 주세요.")
    body.content = (body.content + " " if body.content else "") + f"({'·'.join(sent)} 보냄)"
    return body


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
    order_number: str | None = None   # 내 문의의 주문번호 (없으면 추가 문의에서 받음)
    order_needs_fix: bool = False     # 적은 주문번호로 내 주문을 찾지 못함 → 추가 문의에서 다시 받음
    closed_note: str | None = None    # 답변 없이 종료된 문의 → '종료됨'과 이 문장
    photos_requested: bool = False    # 파손 사진을 나중에 보내기로 함


class InquiryLookupResult(BaseModel):
    items: list[InquiryPublic]  # 최신순
    notice: str                 # 답변 시간 안내
