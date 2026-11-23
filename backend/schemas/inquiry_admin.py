"""문의 관리 API(로그인) 응답 형식 (docs/api_spec.md 4장)."""

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.core import tracing
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
    due_at: UTCDateTime   # 답변 기한 (주말 제외, 긴급 4시간, 그 외 24시간)
    overdue: bool         # 미처리인데 기한을 넘김
    recheck_note: str | None = None          # '확인 후 다시 안내' 표시: 확인할 내용
    recheck_due_at: UTCDateTime | None = None  # 다시 안내할 기한


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
    status: str                       # 기록 / 대기 / 발송 / 실패 / 건너뜀
    error: str | None = None
    sent_at: UTCDateTime | None = None
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


class PointRow(BaseModel):
    at: UTCDateTime
    amount: int
    reason: str
    status: str
    order_number: str | None


class CouponRow(BaseModel):
    name: str
    benefit: str
    min_amount: int
    expires_at: UTCDateTime
    used_at: UTCDateTime | None
    state: str                # 사용 가능 / 사용함 / 만료


class CustomerProfile(BaseModel):
    member: bool              # 쇼핑몰 회원 (로그인 연동 시연 고객)
    phone: str | None         # 가운데를 가린 번호
    orders: int
    inquiries: int            # 이 문의 포함
    negative_inquiries: int   # 부정 감정 문의 수
    negative_ratings: int     # 답변에 '도움 안 됨'(👎)을 준 횟수
    points_balance: int | None = None   # 적립금 잔액 (모의 고객이 아니면 None)
    points_pending: int = 0             # 적립 예정 (구매 확정 전)
    point_history: list[PointRow] = []
    coupons: list[CouponRow] = []


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
    memo: str | None = None
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

    @field_validator("trace_url")
    @classmethod
    def _trace_link(cls, v: str | None) -> str | None:  # 옛 형식으로 저장된 링크도 지금 화면이 여는 형식으로
        return tracing.trace_link(v)

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


class PaymentRow(BaseModel):
    kind: str                 # 승인 / 승인 취소 / 환불
    status: str               # 완료 / 예정
    method: str | None
    amount: int
    approval_no: str | None
    at: UTCDateTime
    memo: str | None


class ShipmentStep(BaseModel):
    at: UTCDateTime
    status: str
    location: str | None


class RelatedInquiry(BaseModel):
    id: int
    inquiry_number: str
    title: str
    status: str
    created_at: UTCDateTime


class OptionChoice(BaseModel):
    option: str
    stock: int = 0
    sold_out: bool
    low: bool = False                      # 재고 3개 이하
    restock_at: UTCDateTime | None = None  # 품절일 때 재입고 예정일 (없으면 미정)
    current: bool


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
    # 상담에 필요한 상세 (2026-11-20)
    quantity: int | None = None
    unit_price: int | None = None
    option: str | None = None
    payment_method: str | None = None
    paid_at: UTCDateTime | None = None
    payments: list[PaymentRow] = []
    duplicate_payment: bool = False       # 같은 금액 승인이 10분 안에 두 번 (승인 취소로 정리되지 않음)
    carrier: str | None = None
    shipment_events: list[ShipmentStep] = []
    return_requested_at: UTCDateTime | None = None
    picked_up_at: UTCDateTime | None = None
    related_inquiries: list[RelatedInquiry] = []   # 같은 주문으로 들어온 다른 문의
    shipping_address: str | None = None
    option_choices: list[OptionChoice] = []        # 옵션별 재고 (옵션 변경·교환 안내)


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
    kind: str  # received / ai / assign / status / draft / sent / ticket / recheck / mail (대화형 화면에서 안내 줄을 고를 때 씀)


class RecheckOut(BaseModel):
    note: str            # 확인할 내용
    due_at: UTCDateTime  # 다시 안내할 기한
    set_at: UTCDateTime | None
    set_by: str
    overdue: bool        # 기한이 지났는데 아직 다시 안내하지 않음


class InquiryDetail(BaseModel):
    id: int
    inquiry_number: str
    customer: CustomerInfo
    customer_profile: CustomerProfile | None = None
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
    recheck: RecheckOut | None = None   # 확인 후 다시 안내 표시
    messages: list[MessageOut]          # 고객 추가 문의
    notes: list[NoteOut]                # 상담원 내부 메모 (고객에게 안 보임)
    attachments: list[AttachmentOut]
    notifications: list[NotificationOut]  # 고객 알림 기록 (시연용)
