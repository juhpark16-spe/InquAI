"""에이전트 실행: LangGraph 처리 흐름(graph.py)을 돌려 결과를 AgentResult로 돌려줍니다.

    표기 재확인 → FAQ 검색 → 규칙 판단 → (LLM 판단) → 주문 본인 확인 → 도구(FAQ 답변·배송 조회·티켓 접수·상담원 이관) → 답변 검사

LLM 오류나 제한 시간 초과는 자동 답변 없이 '답변 초안'(검토 대기)으로 돌리고 오류를 기록합니다.
답변 초안은 여기서 쓰지 않고, 고객에게 응답한 뒤 따로 씁니다 (backend/services/drafts.py, needs_draft).
2주차에 한 함수로 쓰던 흐름을 3주차에 LangGraph로 옮겼고, 결과는 같습니다 (docs/agent_eval.md 비교).
"""

import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backend.agents.graph import AGENT_GRAPH, AgentDeps
from backend.core import tracing
from backend.database.models import Inquiry

STATUS_BY_DECISION = {"자동 답변": "자동 처리", "답변 초안": "검토 대기", "담당자 연결": "담당자 처리"}


@dataclass
class AgentResult:
    decision: str
    decided_by: str
    reason: str
    selected_tool: str | None = None
    tool_success: bool | None = None
    tool_output: dict | None = None
    retrieved_faqs: list = field(default_factory=list)
    used_faq_ids: list = field(default_factory=list)
    answer: str | None = None          # 자동 답변이면 발송, 근거 부족이면 초안, 답변 초안 판단이면 응답 뒤에 채움
    grounded: bool | None = None
    check_points: list = field(default_factory=list)   # 초안에서 상담원이 확인할 것
    llm_model: str | None = None
    tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0, "calls": 0})
    latency_ms: int = 0
    error: str | None = None
    steps: list = field(default_factory=list)          # 지나간 그래프 노드
    trace_url: str | None = None                       # LangSmith 화면 주소 (추적이 켜져 있을 때)
    analysis: dict | None = None                       # 표기 재확인을 거친 최종 분석 (저장·초안에 씀)

    @property
    def status(self) -> str:
        return STATUS_BY_DECISION[self.decision]


def needs_draft(result: AgentResult) -> bool:
    """고객 응답 뒤에 답변 초안을 써야 하는지 (답변 초안 판단인데 아직 글이 없음)"""
    return result.decision == "답변 초안" and result.answer is None and result.error is None


def run_agent(db: Session, inquiry: Inquiry, analysis: dict, faq_search, llm, timeout: float) -> AgentResult:
    start = time.monotonic()
    deps = AgentDeps(db=db, inquiry=inquiry, faq_search=faq_search, llm=llm, deadline=start + timeout)
    run_id = tracing.new_run_id()
    meta = {"inquiry_number": inquiry.inquiry_number, "category": analysis.get("category"),
            "urgency": analysis.get("urgency")}
    try:
        with tracing.trace(metadata=meta, tags=["문의 처리"]):
            s = AGENT_GRAPH.invoke({"text": inquiry.content, "analysis": analysis,
                                    "tokens": {"input": 0, "output": 0, "calls": 0}, "steps": []}, context=deps,
                                   config={"run_id": run_id, "run_name": "문의 처리"})
        result = AgentResult(
            decision=s["decision"], decided_by=s["decided_by"], reason=s["reason"], selected_tool=s.get("selected_tool"),
            tool_success=s.get("tool_success"), tool_output=s.get("tool_output"),
            retrieved_faqs=[[f["id"], round(f["score"], 3)] for f in s.get("retrieved", [])],
            used_faq_ids=s.get("used_faq_ids", []), answer=s.get("answer"), grounded=s.get("grounded"),
            check_points=s.get("check_points", []), llm_model=s.get("llm_model"), tokens=s["tokens"],
            steps=s["steps"], analysis=s["analysis"],
        )
    except Exception as e:  # noqa: BLE001  LLM 오류·시간 초과 등: 고객에게는 접수 안내, 상담원이 검토
        result = AgentResult(decision="답변 초안", decided_by="규칙", reason="에이전트 처리 실패로 상담원 검토",
                             retrieved_faqs=[], error=f"{type(e).__name__}: {e}"[:1000],
                             llm_model=llm.label if llm else None, analysis=analysis)
    result.latency_ms = int((time.monotonic() - start) * 1000)
    result.trace_url = tracing.run_url(run_id)
    return result
