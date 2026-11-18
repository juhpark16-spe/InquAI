"""AI 실행 로그 API 응답 형식."""

from pydantic import BaseModel

from backend.schemas.common import UTCDateTime


class AgentLogRow(BaseModel):
    id: int
    created_at: UTCDateTime
    inquiry_id: int
    inquiry_number: str
    inquiry_title: str
    inquiry_status: str
    category: str
    confidence: float
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
    steps: list | None
    error: str | None


class ToolStat(BaseModel):
    count: int
    failed: int


class AgentLogSummary(BaseModel):
    count: int
    by_decision: dict[str, int]
    by_decided_by: dict[str, int]
    by_tool: dict[str, ToolStat]
    errors: int                    # LLM 오류·시간 초과 (error 칸)
    tool_failures: int             # 도구 실행 실패 (예: 주문 본인 확인 실패)
    low_confidence: int            # 유형 확신도 0.8 미만
    avg_latency_ms: int | None     # LLM이 판단한 문의만 (규칙 판단은 0초)
    max_latency_ms: int | None
    tokens: dict[str, int]         # input, output, calls 합계


class AgentLogPage(BaseModel):
    total: int
    page: int
    size: int
    summary: AgentLogSummary
    items: list[AgentLogRow]
    faq_titles: dict[str, str]     # 목록에 나온 FAQ 번호 → 질문
