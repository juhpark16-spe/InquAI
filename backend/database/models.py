"""DB 테이블 12개 (docs/db_schema.md).

- 모든 테이블에 id(자동 증가)와 created_at(UTC)이 있습니다.
- 상태값처럼 정해진 값은 아래 상수로 모아 두고, API·에이전트 코드도 이 상수를 씁니다.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite는 시간대를 저장하지 않아 읽으면 시간대 없는 값이 됩니다. 비교 전에 UTC로 맞춥니다."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---- 정해진 값 -------------------------------------------------------------
ROLES = ("admin", "agent")
INQUIRY_STATUSES = ("접수", "자동 처리", "검토 대기", "담당자 처리", "완료")
DECISIONS = ("자동 답변", "답변 초안", "담당자 연결")
DECIDED_BY = ("규칙", "LLM")
ROUTES = ("조회형", "접수형", "FAQ형", "이관형")
URGENCIES = ("높음", "보통", "낮음")
RESPONSE_STATUSES = ("초안", "발송")
ORDER_STATUSES = ("결제 완료", "상품 준비 중", "출고", "배송 중", "배송 완료", "취소")
TICKET_TYPES = ("환불", "교환", "취소", "이관")
TICKET_STATUSES = ("접수", "처리 중", "승인", "반려")
TOOLS = ("FAQ 검색", "배송 조회", "티켓 접수", "상담원 이관")
AUDIT_ACTIONS = (
    "login", "login_failed", "logout", "status_change", "assign", "response_edit", "response_approve",
    "ticket_approve", "ticket_reject", "label_correct", "faq_create", "faq_update", "faq_deactivate",
    "user_create", "user_update", "user_password_reset", "auto_assign", "password_change",
)


class TimestampMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- 관리자·상담원 ----------------------------------------------------------
class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"

    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10))
    display_name: Mapped[str] = mapped_column(String(50))
    # 담당 유형 (자동 배정용). 빈 목록이면 '전체 담당': 맞는 담당자가 없는 유형을 받음
    categories: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 비밀번호를 바꾸거나 초기화할 때마다 1씩 올림. access_token 의 ver 가 이 값과 다르면 거부해
    # 다른 기기의 로그인을 즉시 끊음 (시각 비교는 JWT 가 초 단위라 같은 초에 발급된 토큰을 구분하지 못함)
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 기록용


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[int] = mapped_column(ForeignKey("admin_users.id"), index=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdminAuditLog(TimestampMixin, Base):
    __tablename__ = "admin_audit_logs"

    # 없는 아이디로 로그인 실패한 기록은 admin_id 가 비어 있고, 시도한 아이디를 detail 에 남김
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"), index=True)
    action: Mapped[str] = mapped_column(String(30))
    target_type: Mapped[str | None] = mapped_column(String(20))
    target_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSON)


# ---- 고객 문의 --------------------------------------------------------------
class Inquiry(TimestampMixin, Base):
    __tablename__ = "inquiries"
    __table_args__ = (
        Index("ix_inquiries_status_created", "status", "created_at"),
        Index("ix_inquiries_assigned_status", "assigned_to", "status"),
    )

    inquiry_number: Mapped[str] = mapped_column(String(20), unique=True)
    customer_name: Mapped[str] = mapped_column(String(50))
    customer_email: Mapped[str] = mapped_column(String(255), index=True)
    # 고객이 문의할 때 정한 조회 비밀번호의 Argon2 해시 (이메일 + 비밀번호로 조회). 평문은 저장하지 않음
    lookup_password_hash: Mapped[str | None] = mapped_column(String(255))
    order_number: Mapped[str | None] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="접수")
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    assignee: Mapped[AdminUser | None] = relationship()
    analysis: Mapped["AnalysisResult | None"] = relationship(back_populates="inquiry", uselist=False)
    responses: Mapped[list["Response"]] = relationship(back_populates="inquiry", order_by="Response.id")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="inquiry")
    agent_logs: Mapped[list["AgentLog"]] = relationship(back_populates="inquiry", order_by="AgentLog.id")


class AnalysisResult(TimestampMixin, Base):
    __tablename__ = "analysis_results"
    __table_args__ = (Index("ix_analysis_urgency_category", "urgency", "category"),)

    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), unique=True)
    category: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    sentiment: Mapped[str] = mapped_column(String(5))
    sentiment_confidence: Mapped[float] = mapped_column(Float)
    urgency: Mapped[str] = mapped_column(String(5))
    route: Mapped[str] = mapped_column(String(5))
    decision: Mapped[str | None] = mapped_column(String(10))
    decided_by: Mapped[str | None] = mapped_column(String(5))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(String(50))
    scores: Mapped[dict | None] = mapped_column(JSON)

    inquiry: Mapped[Inquiry] = relationship(back_populates="analysis")


class Response(TimestampMixin, Base):
    __tablename__ = "responses"

    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    draft_text: Mapped[str] = mapped_column(Text)
    final_text: Mapped[str | None] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(20), default="llm")
    used_faq_ids: Mapped[list] = mapped_column(JSON, default=list)
    grounded: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(10), default="초안")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False)

    inquiry: Mapped[Inquiry] = relationship(back_populates="responses")


class LabelCorrection(TimestampMixin, Base):
    __tablename__ = "label_corrections"

    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    field: Mapped[str] = mapped_column(String(10))
    before_label: Mapped[str] = mapped_column(String(20))
    after_label: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    corrected_by: Mapped[int] = mapped_column(ForeignKey("admin_users.id"))


class AgentLog(TimestampMixin, Base):
    __tablename__ = "agent_logs"
    __table_args__ = (Index("ix_agent_logs_inquiry_created", "inquiry_id", "created_at"),)

    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"))
    category: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(10))
    decided_by: Mapped[str] = mapped_column(String(5))
    selected_tool: Mapped[str | None] = mapped_column(String(10))
    tool_success: Mapped[bool | None] = mapped_column(Boolean)
    tool_output: Mapped[dict | None] = mapped_column(JSON)
    retrieved_faqs: Mapped[list] = mapped_column(JSON, default=list)
    used_faq_ids: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str | None] = mapped_column(Text)
    response_text: Mapped[str | None] = mapped_column(Text)
    llm_model: Mapped[str | None] = mapped_column(String(50))
    tokens: Mapped[dict | None] = mapped_column(JSON)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    trace_url: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)

    inquiry: Mapped[Inquiry] = relationship(back_populates="agent_logs")


# ---- FAQ -------------------------------------------------------------------
class Faq(TimestampMixin, Base):
    __tablename__ = "faqs"

    code: Mapped[str] = mapped_column(String(10), unique=True)
    category: Mapped[str] = mapped_column(String(20), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---- 모의 고객·주문·티켓 -----------------------------------------------------
class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    phone: Mapped[str] = mapped_column(String(20))

    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(30), unique=True)  # unique가 인덱스 역할
    product_name: Mapped[str] = mapped_column(String(200))
    amount: Mapped[int] = mapped_column(Integer)
    order_status: Mapped[str] = mapped_column(String(10))
    shipping_status: Mapped[str | None] = mapped_column(String(20))
    tracking_number: Mapped[str | None] = mapped_column(String(30))
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    customer: Mapped[Customer] = relationship(back_populates="orders")


class Ticket(TimestampMixin, Base):
    __tablename__ = "tickets"

    inquiry_id: Mapped[int] = mapped_column(ForeignKey("inquiries.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    ticket_type: Mapped[str] = mapped_column(String(5))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(5), default="접수")
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id"))
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    inquiry: Mapped[Inquiry] = relationship(back_populates="tickets")
    order: Mapped[Order | None] = relationship()
