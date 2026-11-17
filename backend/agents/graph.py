"""에이전트 처리 흐름 (LangGraph, 3주차). 고객이 기다리는 부분만 그래프로 돌리고, 답변 초안은 응답 뒤에 씁니다.

    START → FAQ 검색 → 규칙 판단 ─┬─(정해짐)──────────────┐
                                  └─(아님)→ LLM 판단 ──────┤
                                                           ▼
                                                     주문 본인 확인
              ┌──────────────┬──────────────┬──────────────┼──────────────┐
          FAQ 답변 →     배송 조회      티켓 접수     상담원 이관    FAQ 기록(초안 대상)
          답변 검사          │              │              │              │
              └──────────────┴──────────────┴──────────────┴──────────────┴→ END

- 노드는 상태(AgentState)의 바뀐 부분만 돌려줍니다. DB 세션·문의·검색·LLM·마감 시각은 실행 정보(AgentDeps)로 받습니다.
- 그림: docs/agent_graph.md (python -m backend.agents.graph 로 다시 그림)
- 답변 초안은 이 그래프 밖에서 고객 응답 뒤에 씀 (backend/services/drafts.py, 응답 시간·20초 제한 문제 때문)
"""

import operator
import time
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from sqlalchemy.orm import Session

from backend.ai.prompts import (ANSWER_PROMPT, ANSWER_SCHEMA, ROUTE_PROMPT, ROUTE_SCHEMA, decide_by_rule,
                                find_promises, format_answer_input, format_route_input)
from backend.database.models import Inquiry, Order
from backend.tools.orders import find_customer_order, shipping_summary
from backend.tools.tickets import CATEGORY_TICKET_TYPE, create_ticket

ORDER_TOOLS = {"배송 조회", "티켓 접수"}


def _add_tokens(a: dict, b: dict) -> dict:
    """LLM을 부른 노드마다 토큰을 더함 (LangGraph 리듀서)"""
    return {k: a.get(k, 0) + b.get(k, 0) for k in {"input", "output", "calls"}}


class AgentState(TypedDict, total=False):
    text: str
    analysis: dict
    retrieved: list[dict]             # 검색된 FAQ (점수 포함)
    plan: dict                        # {decision, tool, faq_ids, reason}
    decided_by: str                   # 규칙 / LLM
    order_id: int | None              # 본인 확인된 주문
    decision: str
    reason: str
    selected_tool: str | None
    tool_success: bool | None
    tool_output: dict | None
    answer: str | None                # 자동 답변 (근거 부족·확정 표현이면 초안으로 내림)
    grounded: bool | None
    used_faq_ids: list[str]
    check_points: list[str]
    llm_model: str | None
    tokens: Annotated[dict, _add_tokens]
    steps: Annotated[list[str], operator.add]   # 지나간 노드 (실행 기록·디버깅용)


@dataclass
class AgentDeps:
    db: Session
    inquiry: Inquiry
    faq_search: Any
    llm: Any
    deadline: float                   # time.monotonic() 기준 마감 시각

    def ask_llm(self, system: str, user: str, schema: dict, name: str) -> tuple[dict, dict]:
        if self.llm is None:
            raise RuntimeError("LLM을 쓸 수 없습니다 (OPENAI_API_KEY 없음).")
        remaining = self.deadline - time.monotonic()
        if remaining <= 1:
            raise TimeoutError("에이전트 처리 시간 초과")
        data, usage = self.llm.json(system, user, schema, name, timeout=remaining)
        return data, {"input": usage.get("input", 0), "output": usage.get("output", 0), "calls": 1}


Ctx = Runtime[AgentDeps]


# ---- 노드 -------------------------------------------------------------------
def search_faq(state: AgentState, runtime: Ctx) -> dict:
    return {"retrieved": runtime.context.faq_search.search(state["text"]), "steps": ["FAQ 검색"]}


def rule_check(state: AgentState, runtime: Ctx) -> dict:
    a = state["analysis"]
    plan = decide_by_rule(a["route"], a["urgency"], a["confidence"])
    return {"plan": plan, "decided_by": "규칙", "steps": ["규칙 판단"]} if plan else {"steps": ["규칙 판단"]}


def llm_route(state: AgentState, runtime: Ctx) -> dict:
    deps = runtime.context
    plan, tokens = deps.ask_llm(ROUTE_PROMPT, format_route_input(state["text"], state["analysis"], state["retrieved"]),
                                ROUTE_SCHEMA, "route")
    return {"plan": plan, "decided_by": "LLM", "tokens": tokens, "llm_model": deps.llm.label, "steps": ["LLM 판단"]}


def verify_order(state: AgentState, runtime: Ctx) -> dict:
    """배송 조회·티켓 접수 전에 주문번호와 문의 이메일이 맞는지 확인 (아니면 담당자에게)"""
    inquiry, plan, out = runtime.context.inquiry, state["plan"], {}
    order = None
    if plan["tool"] in ORDER_TOOLS and inquiry.order_number:
        order = find_customer_order(runtime.context.db, inquiry.order_number, inquiry.customer_email)
        if order is None:
            plan = {"decision": "담당자 연결", "tool": "상담원 이관", "faq_ids": [],
                    "reason": "주문번호와 이메일이 일치하지 않음"}
            out["decided_by"] = "규칙"
    return {**out, "plan": plan, "order_id": order.id if order else None, "decision": plan["decision"],
            "reason": plan["reason"], "selected_tool": plan["tool"], "steps": ["주문 본인 확인"]}


def faq_answer(state: AgentState, runtime: Ctx) -> dict:
    deps = runtime.context
    chosen = [f for f in state["retrieved"] if f["id"] in state["plan"]["faq_ids"]] or state["retrieved"]
    ans, tokens = deps.ask_llm(ANSWER_PROMPT, format_answer_input(state["text"], chosen), ANSWER_SCHEMA, "answer")
    return {"selected_tool": "FAQ 검색", "answer": ans["answer"], "grounded": ans["grounded"],
            "used_faq_ids": ans["used_faq_ids"], "tool_success": True,
            "tool_output": {"faq_ids": [f["id"] for f in chosen]}, "tokens": tokens, "llm_model": deps.llm.label,
            "steps": ["FAQ 답변"]}


def check_answer(state: AgentState, runtime: Ctx) -> dict:
    """자동 답변 검사: FAQ 근거가 부족하거나 지급·승인을 확정하는 말이 있으면 보내지 않고 초안으로"""
    if not state["grounded"]:
        return {"decision": "답변 초안", "reason": state["reason"] + " / FAQ 근거 부족으로 초안 전환", "steps": ["답변 검사"]}
    if promises := find_promises(state["answer"]):
        return {"decision": "답변 초안", "grounded": False, "steps": ["답변 검사"],
                "reason": state["reason"] + " / 지급·승인을 확정하는 표현이 있어 초안 전환",
                "check_points": [f"지급·승인을 확정하는 표현이 있습니다: '{p}' (사실인지 확인 후 고치세요)" for p in promises]}
    return {"steps": ["답변 검사"]}


def _order(state: AgentState, runtime: Ctx) -> Order | None:
    return runtime.context.db.get(Order, state["order_id"]) if state.get("order_id") else None


def lookup_shipping(state: AgentState, runtime: Ctx) -> dict:
    order = _order(state, runtime)
    if order is None:
        return {"tool_success": False, "tool_output": {"message": "주문번호 없음 (상담원이 고객에게 확인)"},
                "steps": ["배송 조회"]}
    return {"tool_success": True, "tool_output": shipping_summary(order), "steps": ["배송 조회"]}


def open_ticket(state: AgentState, runtime: Ctx) -> dict:
    deps, order = runtime.context, _order(state, runtime)
    ticket_type = CATEGORY_TICKET_TYPE.get(state["analysis"]["category"])
    if order is None or ticket_type is None:
        return {"tool_success": False, "steps": ["티켓 접수"],
                "tool_output": {"message": "주문번호 없음 (상담원이 고객에게 확인)" if order is None
                                else f"{state['analysis']['category']} 유형은 티켓 종류가 정해지지 않음"}}
    ticket = create_ticket(deps.db, deps.inquiry, ticket_type, reason=state["text"], order=order)
    return {"tool_success": True, "tool_output": {"ticket_id": ticket.id, "ticket_type": ticket_type, **shipping_summary(order)},
            "steps": ["티켓 접수"]}


def escalate(state: AgentState, runtime: Ctx) -> dict:
    ticket = create_ticket(runtime.context.db, runtime.context.inquiry, "이관", reason=state["plan"]["reason"])
    return {"tool_success": True, "tool_output": {"ticket_id": ticket.id}, "steps": ["상담원 이관"]}


def record_faqs(state: AgentState, runtime: Ctx) -> dict:
    """답변 초안 + FAQ 검색 (FAQ형): 검색 결과만 기록. 초안은 응답 뒤에 씀"""
    ids = state["plan"]["faq_ids"] or [f["id"] for f in state["retrieved"]]
    return {"tool_success": True, "tool_output": {"faq_ids": ids}, "steps": ["FAQ 기록"]}


# ---- 갈림길 -----------------------------------------------------------------
def after_rule(state: AgentState) -> str:
    return "verify_order" if state.get("plan") else "llm_route"


def pick_tool(state: AgentState) -> str:
    plan = state["plan"]
    if plan["decision"] == "자동 답변":
        return "faq_answer"
    return {"배송 조회": "lookup_shipping", "티켓 접수": "open_ticket", "상담원 이관": "escalate"}.get(plan["tool"],
                                                                                               "record_faqs")


def build_graph():
    g = StateGraph(AgentState, context_schema=AgentDeps)
    for name, fn in [("search_faq", search_faq), ("rule_check", rule_check), ("llm_route", llm_route),
                     ("verify_order", verify_order), ("faq_answer", faq_answer), ("check_answer", check_answer),
                     ("lookup_shipping", lookup_shipping), ("open_ticket", open_ticket), ("escalate", escalate),
                     ("record_faqs", record_faqs)]:
        g.add_node(name, fn)
    g.add_edge(START, "search_faq")
    g.add_edge("search_faq", "rule_check")
    g.add_conditional_edges("rule_check", after_rule, ["verify_order", "llm_route"])
    g.add_edge("llm_route", "verify_order")
    g.add_conditional_edges("verify_order", pick_tool,
                            ["faq_answer", "lookup_shipping", "open_ticket", "escalate", "record_faqs"])
    g.add_edge("faq_answer", "check_answer")
    for end in ("check_answer", "lookup_shipping", "open_ticket", "escalate", "record_faqs"):
        g.add_edge(end, END)
    return g.compile()


AGENT_GRAPH = build_graph()


NODE_LABELS = {  # 노드 이름 → 화면·문서에 쓰는 이름과 하는 일
    "search_faq": ("FAQ 검색", "KURE + ChromaDB로 비슷한 FAQ 3개"),
    "rule_check": ("규칙 판단", "확신도 0.8 미만·긴급도 높음·기타 유형이면 LLM 없이 담당자 연결"),
    "llm_route": ("LLM 판단", "처리 방식(자동 답변/답변 초안/담당자 연결)과 도구 선택"),
    "verify_order": ("주문 본인 확인", "주문번호와 문의 이메일이 다르면 담당자 연결"),
    "faq_answer": ("FAQ 답변", "검색된 FAQ만 근거로 자동 답변 작성"),
    "check_answer": ("답변 검사", "근거 부족·지급/승인 확정 표현이면 보내지 않고 초안으로"),
    "lookup_shipping": ("배송 조회", "본인 주문의 배송 상태"),
    "open_ticket": ("티켓 접수", "취소·교환·환불 티켓"),
    "escalate": ("상담원 이관", "이관 티켓"),
    "record_faqs": ("FAQ 기록", "답변 초안 대상: 검색 결과만 기록 (초안은 고객 응답 뒤)"),
}


if __name__ == "__main__":  # 그림 다시 그리기: docs/agent_graph.md
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "docs" / "agent_graph.md"
    rows = "\n".join(f"| `{k}` | {v[0]} | {v[1]} |" for k, v in NODE_LABELS.items())
    path.write_text(
        "# 에이전트 처리 흐름 (LangGraph)\n\n"
        "`backend/agents/graph.py`에서 자동으로 그린 그림입니다 (`python -m backend.agents.graph`). "
        "점선은 상태에 따라 갈라지는 길(조건 분기)입니다.\n\n"
        "답변 초안은 이 그래프 밖에서, 고객에게 응답한 뒤 씁니다 (`backend/services/drafts.py`).\n\n"
        "```mermaid\n" + AGENT_GRAPH.get_graph().draw_mermaid() + "```\n\n"
        "| 노드 | 이름 | 하는 일 |\n| --- | --- | --- |\n" + rows + "\n", encoding="utf-8")
    print(f"저장: {path}")
