"""문의 관리 API(로그인) 응답 형식 (docs/api_spec.md 4장)."""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from backend.schemas.common import UTCDateTime

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Assignee(ORM):
    id: int
    display_name: str


class InquiryListItem(BaseModel):
    id: int
    inquiry_number: str
    title: str
    customer_name: str
    status: str
    category: str | None
    urgency: str | None
    sentiment: str | None
    decision: str | None
    assigned_to: Assignee | None
    created_at: UTCDateTime


class AssignRequest(BaseModel):
    assigned_to: int | None  # null 이면 배정 해제


# 사람이 바꿀 수 있는 상태. '접수'·'자동 처리'는 시스템(에이전트)만 정함
MANUAL_STATUSES = ("검토 대기", "담당자 처리", "완료")


class StatusRequest(BaseModel):
    status: Literal[MANUAL_STATUSES]


class InquiryState(BaseModel):
    """배정·상태 변경 API의 응답"""
    id: int
    inquiry_number: str
    status: str
    assigned_to: Assignee | None
    updated_at: UTCDateTime


class CustomerInfo(BaseModel):
    name: str
    email: str
    order_number: str | None


class AnalysisOut(ORM):
    category: str
    confidence: float
    sentiment: str
    sentiment_confidence: float
    urgency: str
    route: str
    decision: str | None
    decided_by: str | None
    decision_reason: str | None
    scores: dict | None
    model_version: str


class ResponseOut(ORM):
    id: int
    draft_text: str
    final_text: str | None
    generated_by: str
    status: str
    used_faq_ids: list
    grounded: bool | None
    is_edited: bool
    approved_by: int | None
    approved_at: UTCDateTime | None
    created_at: UTCDateTime


class TicketOut(ORM):
    id: int
    ticket_type: str
    order_id: int | None
    reason: str
    status: str
    handled_by: int | None
    handled_at: UTCDateTime | None
    created_at: UTCDateTime


class AgentLogOut(ORM):
    id: int
    decision: str
    decided_by: str
    selected_tool: str | None
    tool_success: bool | None
    tool_output: dict | None
    retrieved_faqs: list
    used_faq_ids: list
    reason: str | None
    response_text: str | None
    llm_model: str | None
    tokens: dict | None
    latency_ms: int | None
    trace_url: str | None
    error: str | None
    created_at: UTCDateTime


class CorrectionOut(ORM):
    id: int
    field: str
    before_label: str
    after_label: str
    corrected_by: int
    created_at: UTCDateTime


class InquiryDetail(BaseModel):
    id: int
    inquiry_number: str
    customer: CustomerInfo
    title: str
    content: str
    status: str
    assigned_to: Assignee | None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    analysis: AnalysisOut | None
    responses: list[ResponseOut]
    tickets: list[TicketOut]
    agent_logs: list[AgentLogOut]
    corrections: list[CorrectionOut]
