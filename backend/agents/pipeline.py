"""에이전트 처리 흐름 (2주차 최소 버전, 3주차에 LangGraph 그래프로 옮깁니다).

    규칙 판단(확신도·긴급도·기타) ─┬─ 정해지면 그대로
                                   └─ 아니면 LLM 처리 방식 판단 (prompts.ROUTE_PROMPT)
    → 주문 본인 확인 (배송 조회·티켓 접수 전에, 주문번호가 있을 때)
    → 도구 실행: FAQ 답변 생성 / 배송 조회 / 티켓 접수 / 상담원 이관
    → 자동 답변인데 FAQ 근거가 부족하면 초안으로 내림

1주차 프롬프트 검증(backend/ai/prompt_check.py)과 같은 순서·같은 프롬프트를 씁니다.
LLM 오류나 제한 시간 초과는 자동 답변 없이 '답변 초안'(검토 대기)으로 돌리고 오류를 기록합니다.
"""

import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backend.ai.prompts import (ANSWER_PROMPT, ANSWER_SCHEMA, ROUTE_PROMPT, ROUTE_SCHEMA, decide_by_rule,
                                format_answer_input, format_route_input)
from backend.database.models import Inquiry
from backend.tools.orders import find_customer_order, shipping_summary
from backend.tools.tickets import CATEGORY_TICKET_TYPE, create_ticket

STATUS_BY_DECISION = {"자동 답변": "자동 처리", "답변 초안": "검토 대기", "담당자 연결": "담당자 처리"}
ORDER_TOOLS = {"배송 조회", "티켓 접수"}


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
    answer: str | None = None          # LLM이 만든 답변 (자동 답변이면 발송, 근거 부족이면 초안)
    grounded: bool | None = None
    llm_model: str | None = None
    tokens: dict = field(default_factory=lambda: {"input": 0, "output": 0, "calls": 0})
    latency_ms: int = 0
    error: str | None = None

    @property
    def status(self) -> str:
        return STATUS_BY_DECISION[self.decision]


def _escalate(reason: str) -> dict:
    return {"decision": "담당자 연결", "tool": "상담원 이관", "faq_ids": [], "reason": reason}


def run_agent(db: Session, inquiry: Inquiry, analysis: dict, faq_search, llm, timeout: float) -> AgentResult:
    start = time.monotonic()
    text = inquiry.content
    retrieved = faq_search.search(text)
    result = AgentResult(decision="답변 초안", decided_by="규칙", reason="",
                         retrieved_faqs=[[f["id"], round(f["score"], 3)] for f in retrieved])

    def ask_llm(system, user, schema, name):
        if llm is None:
            raise RuntimeError("LLM을 쓸 수 없습니다 (OPENAI_API_KEY 없음).")
        remaining = timeout - (time.monotonic() - start)
        if remaining <= 1:
            raise TimeoutError(f"에이전트 처리 시간 {timeout:.0f}초 초과")
        result.llm_model = llm.label
        data, usage = llm.json(system, user, schema, name, timeout=remaining)
        result.tokens["input"] += usage.get("input", 0)
        result.tokens["output"] += usage.get("output", 0)
        result.tokens["calls"] += 1
        return data

    try:
        # 1. 규칙 → 2. LLM 처리 방식 판단
        plan = decide_by_rule(analysis["route"], analysis["urgency"], analysis["confidence"])
        if plan is None:
            plan = ask_llm(ROUTE_PROMPT, format_route_input(text, analysis, retrieved), ROUTE_SCHEMA, "route")
            result.decided_by = "LLM"

        # 3. 주문 본인 확인: 주문번호와 이메일이 맞지 않으면 도구를 실행하지 않고 담당자에게
        order = None
        if plan["tool"] in ORDER_TOOLS and inquiry.order_number:
            order = find_customer_order(db, inquiry.order_number, inquiry.customer_email)
            if order is None:
                plan = _escalate("주문번호와 이메일이 일치하지 않음")
                result.decided_by = "규칙"

        result.decision, result.reason, result.selected_tool = plan["decision"], plan["reason"], plan["tool"]

        # 4. 도구 실행
        if plan["decision"] == "자동 답변":
            chosen = [f for f in retrieved if f["id"] in plan["faq_ids"]] or retrieved
            ans = ask_llm(ANSWER_PROMPT, format_answer_input(text, chosen), ANSWER_SCHEMA, "answer")
            result.selected_tool = "FAQ 검색"
            result.answer, result.grounded = ans["answer"], ans["grounded"]
            result.used_faq_ids = ans["used_faq_ids"]
            result.tool_success, result.tool_output = True, {"faq_ids": [f["id"] for f in chosen]}
            if not ans["grounded"]:  # 근거가 부족하면 자동 발송하지 않고 초안으로
                result.decision = "답변 초안"
                result.reason += " / FAQ 근거 부족으로 초안 전환"

        elif plan["tool"] == "배송 조회":
            if order is None:
                result.tool_success, result.tool_output = False, {"message": "주문번호 없음 (상담원이 고객에게 확인)"}
            else:
                result.tool_success, result.tool_output = True, shipping_summary(order)

        elif plan["tool"] == "티켓 접수":
            ticket_type = CATEGORY_TICKET_TYPE.get(analysis["category"])
            if order is None or ticket_type is None:
                result.tool_success = False
                result.tool_output = {"message": "주문번호 없음 (상담원이 고객에게 확인)" if order is None
                                      else f"{analysis['category']} 유형은 티켓 종류가 정해지지 않음"}
            else:
                ticket = create_ticket(db, inquiry, ticket_type, reason=text, order=order)
                result.tool_success = True
                result.tool_output = {"ticket_id": ticket.id, "ticket_type": ticket_type, **shipping_summary(order)}

        elif plan["tool"] == "상담원 이관":
            ticket = create_ticket(db, inquiry, "이관", reason=plan["reason"])
            result.tool_success, result.tool_output = True, {"ticket_id": ticket.id}

        else:  # 답변 초안 + FAQ 검색 (FAQ형): 검색 결과만 기록, 초안 작성은 3주차
            result.tool_success = True
            result.tool_output = {"faq_ids": plan["faq_ids"] or [f["id"] for f in retrieved]}

    except Exception as e:  # noqa: BLE001  LLM 오류·시간 초과 등: 고객에게는 접수 안내, 상담원이 검토
        result.decision, result.decided_by = "답변 초안", "규칙"
        result.reason = "에이전트 처리 실패로 상담원 검토"
        result.answer = result.grounded = None
        result.used_faq_ids = []
        result.error = f"{type(e).__name__}: {e}"[:1000]

    result.latency_ms = int((time.monotonic() - start) * 1000)
    return result
