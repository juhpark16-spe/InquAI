"""문의 관리 API(로그인) 응답 형식 (docs/api_spec.md 4장)."""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.schemas.common import UTCDateTime
from backend.training.labels import CATEGORY_LABELS, SENTIMENT_LABELS

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
    confidence: float | None  # AI 유형 분류 확신도 (0~1, 낮으면 사람이 확인)
    assigned_to: Assignee | None
    created_at: UTCDateTime
    due_at: UTCDateTime   # 답변 기한 (긴급 4시간, 그 외 24시간)
    overdue: bool         # 미처리인데 기한을 넘김


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class NoteOut(BaseModel):
    id: int
    author: str
    text: str
    created_at: UTCDateTime


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size: int
    message_id: int | None  # 추가 문의에 붙은 사진이면 그 메시지
    created_at: UTCDateTime


class MessageOut(BaseModel):
    id: int
    text: str
    created_at: UTCDateTime


class NotificationOut(BaseModel):
    channel: str
    recipient: str
    subject: str
    status: str
    created_at: UTCDateTime


class AnalysisCorrection(BaseModel):
    """분류 결과 수정 (재학습 데이터). 바꿀 것만 보냄"""
    category: Literal[tuple(CATEGORY_LABELS)] | None = None  # type: ignore[valid-type]
    sentiment: Literal[tuple(SENTIMENT_LABELS)] | None = None  # type: ignore[valid-type]

    @model_validator(mode="after")
    def _one_or_more(self):
        if self.category is None and self.sentiment is None:
            raise ValueError("고칠 유형이나 감정을 하나 이상 골라 주세요.")
        return self


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
    rating: int | None = None  # 고객 평가 1 / -1
    check_points: list | None = None  # AI 초안에서 상담원이 확인할 것
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
    steps: list | None = None  # 처리 경로 (LangGraph 노드)
    created_at: UTCDateTime


class CorrectionOut(ORM):
    id: int
    field: str            # category / sentiment
    before_label: str     # 고치기 전 (처음이면 모델 예측)
    after_label: str      # 상담원이 고른 정답
    corrected_by: int
    created_at: UTCDateTime


class OrderCard(BaseModel):
    found: bool
    order_number: str
    email_match: bool | None = None
    orderer: str | None = None
    product_name: str | None = None
    amount: int | None = None
    order_status: str | None = None
    shipping_status: str | None = None
    tracking_number: str | None = None
    ordered_at: UTCDateTime | None = None
    delivered_at: UTCDateTime | None = None
    cancellable: bool | None = None
    return_until: UTCDateTime | None = None
    returnable: bool | None = None
    defect_return_until: UTCDateTime | None = None


class HistoryItem(BaseModel):
    id: int
    inquiry_number: str
    title: str
    status: str
    created_at: UTCDateTime


class Event(BaseModel):
    at: UTCDateTime
    actor: str
    text: str
    kind: str  # received / ai / assign / status / draft / sent (대화형 화면에서 안내 줄을 고를 때 씀)


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
    order: OrderCard | None
    email_orders: list[OrderCard]  # 문의 이메일로 찾은 다른 주문 (본인 확인 필요)
    customer_history: list[HistoryItem]
    faq_titles: dict[str, str]
    history: list[Event]
    due_at: UTCDateTime
    overdue: bool
    messages: list[MessageOut]          # 고객 추가 문의
    notes: list[NoteOut]                # 상담원 내부 메모 (고객에게 안 보임)
    attachments: list[AttachmentOut]
    notifications: list[NotificationOut]  # 고객 알림 기록 (시연용)
