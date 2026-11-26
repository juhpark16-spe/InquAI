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
    note_count: int = 0                        # 상담원 공유 메모 개수
    new_follow_up: bool = False                # 마지막 답변 뒤 고객 추가 문의가 있음
    bad_rating: bool = False                   # 보낸 답변에 고객 👎


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class NoteOut(BaseModel):
    id: int
    author: str
    author_id: int | None = None   # 화면에서 내 메모인지 가림 ('New' 배지는 다른 사람 메모에만)
    text: str
    created_at: UTCDateTime


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size: int
    message_id: int | None  # 추가 문의에 붙은 사진이면 그 메시지
    label: str | None = None  # 파손 문의의 사진 칸: 송장 / 파손 부위
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
    memo: str | None = Field(None, max_length=500)   # 넘기기(인계) 메모: 상담원이 다른 상담원에게 넘길 때 필수


# 사람이 바꿀 수 있는 상태. '접수'·'자동 처리'는 시스템(에이전트)만 정함
MANUAL_STATUSES = ("검토 대기", "담당자 처리", "완료")


# 완료 사유. "답변으로 해결"은 답변을 보낸 문의 (고객 화면은 그대로 '답변 완료'), 나머지는 '종료됨'과 안내가 보임
CLOSE_REASONS = ("답변으로 해결", "중복 문의", "스팸·광고", "고객 철회", "전화로 안내", "기타")


class StatusRequest(BaseModel):
    status: Literal[MANUAL_STATUSES]
    reason: Literal[CLOSE_REASONS] | None = None   # '완료'로 바꿀 때 사유 (화면은 꼭 받음)


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
    customer_id: int | None = None   # 쇼핑몰 고객 번호 (고객 조회 화면 링크, 주문한 적 없는 이메일이면 None)
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


class OrderHint(BaseModel):
    order_number: str
    found: bool          # 실제 주문이 있음
    email_match: bool    # 주문자 이메일 = 문의 이메일
    product_name: str | None = None


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
    carrier_info: dict | None = None        # {name, phone(대표번호), tracking_url(배송조회)} (services/carriers.py)
    driver: dict | None = None              # 배송 출발 뒤 담당 기사 {name, phone(가운데 가림)}
    shipment_events: list[ShipmentStep] = []
    return_requested_at: UTCDateTime | None = None
    picked_up_at: UTCDateTime | None = None
    return_reason: str | None = None        # [반품 회수 접수]에서 고른 사유 (단순 변심 / 불량·오배송)
    refund_preview: int | None = None       # 반품 승인 시 환불 예정 금액 (단순 변심이면 왕복 배송비 차감)
    exchange_fee: dict | None = None        # 단순 변심 교환 배송비: {amount, status(요청/완료), method, at}
    points_balance: int | None = None       # 고객 적립금 잔액 (교환 배송비를 적립금으로 받을 수 있는지)
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
    order_hints: list[OrderHint] = []  # 고객 글·추가 문의에 적힌 다른 주문번호
    customer_history: list[HistoryItem]
    customer_history_hidden: dict[str, int] = {}   # 상담원: 남이 맡은(또는 미배정) 같은 고객 문의 수 {total, open}
    refund_account: dict | None = None             # 환불 계좌 (가림), 전체 번호는 GET /refund-account
    refund_account_needed: bool = False            # 무통장입금 취소·반품인데 환불 계좌가 아직 없음
    faq_titles: dict[str, str]
    history: list[Event]
    due_at: UTCDateTime
    overdue: bool
    recheck: RecheckOut | None = None   # 확인 후 다시 안내 표시
    photo_request: str | None = None    # '나중에': 파손 문의인데 고객이 사진을 나중에 보내기로 함
    close_reason: str | None = None     # 답변 없이 종료한 사유
    messages: list[MessageOut]          # 고객 추가 문의
    notes: list[NoteOut]                # 상담원 공유 메모 (고객에게 안 보임)
    attachments: list[AttachmentOut]
    notifications: list[NotificationOut]  # 고객 알림 기록 (시연용)
