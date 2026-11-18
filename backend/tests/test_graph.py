"""LangGraph 처리 흐름: 그래프 모양, 문의마다 지나간 단계, 초안은 응답 뒤에"""

from sqlalchemy import select

from backend.agents.graph import AGENT_GRAPH
from backend.database.models import AgentLog, Response
from backend.tests.test_drafting import DRAFT
from backend.tests.test_inquiries import ai, post, route_reply, saved  # noqa: F401  (fixture 재사용)


def test_graph_shape():
    g = AGENT_GRAPH.get_graph()
    nodes = set(g.nodes) - {"__start__", "__end__"}
    assert nodes == {"search_faq", "rule_check", "llm_route", "verify_order", "faq_answer", "check_answer",
                     "lookup_shipping", "open_ticket", "escalate", "record_faqs"}
    mermaid = g.draw_mermaid()
    assert "rule_check" in mermaid and "llm_route" in mermaid


def steps_of(db, number):
    return saved(db, number)[1].steps


def test_rule_path_skips_llm(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.6}
    number = post(client).json()["inquiry_number"]
    assert steps_of(db, number) == ["FAQ 검색", "규칙 판단", "주문 본인 확인", "상담원 이관"]
    assert ai["llm"].calls == []


def test_auto_answer_path(client, db, ai):
    ai["llm"].replies = {"route": route_reply("자동 답변", "FAQ 검색", ["F05"]),
                         "answer": {"answer": "보통 1~3일 걸립니다.", "used_faq_ids": ["F05"], "grounded": True}}
    number = post(client).json()["inquiry_number"]
    assert steps_of(db, number) == ["FAQ 검색", "규칙 판단", "LLM 판단", "주문 본인 확인", "FAQ 답변", "답변 검사"]


def test_other_persons_order_goes_to_staff(client, db, ai):
    ai["llm"].replies = {"route": route_reply("답변 초안", "배송 조회")}
    number = post(client, order_number="20261110-0001", customer_email="someone@example.com").json()["inquiry_number"]
    inquiry, log = saved(db, number)
    assert inquiry.status == "담당자 처리" and log.decided_by == "규칙"
    assert log.steps[-2:] == ["주문 본인 확인", "상담원 이관"]


def test_draft_is_written_after_response(client, db, ai):
    """답변 초안 판단: 고객 응답에는 초안 시간이 들지 않고(별도 작업), 초안은 응답 뒤에 저장됨"""
    ai["llm"].replies = {"route": route_reply("답변 초안", "FAQ 검색"), "draft": DRAFT}
    body = post(client).json()
    inquiry, log = saved(db, body["inquiry_number"])
    assert log.steps[-1] == "FAQ 기록" and "초안" not in "".join(log.steps)   # 그래프에는 초안 단계가 없음
    assert ai["llm"].calls == ["route", "draft"]                               # 판단 → (응답 뒤) 초안
    draft = db.scalar(select(Response).where(Response.inquiry_id == inquiry.id))
    assert draft.status == "초안" and log.response_text == draft.draft_text
    assert "draft_ms" in log.tool_output


def test_tool_check_fixes_tool_that_does_not_fit_route(client, db, ai):
    """결제(FAQ형) 문의 초안에 LLM이 '티켓 접수'를 고르면 코드가 FAQ 검색으로 바꿈 (기획서 2-2의 4번)"""
    from backend.database.models import Ticket

    ai["analyzer"].next = {"category": "결제"}
    ai["llm"].replies = {"route": route_reply("답변 초안", "티켓 접수", reason="입금 확인 필요"),
                         "draft": DRAFT}
    number = post(client, content="남편 이름으로 입금했는데 미확인이에요").json()["inquiry_number"]
    inquiry, log = saved(db, number)
    assert log.selected_tool == "FAQ 검색" and "도구 확인: 티켓 접수 → FAQ 검색" in log.reason
    assert log.steps[:5] == ["FAQ 검색", "규칙 판단", "LLM 판단", "도구 확인", "주문 본인 확인"]
    assert db.scalars(select(Ticket).where(Ticket.inquiry_id == inquiry.id)).all() == []   # 엉뚱한 티켓을 만들지 않음


def test_check_tool_table():
    from backend.ai.prompts import check_tool

    plan = lambda d, t: {"decision": d, "tool": t, "faq_ids": [], "reason": "r"}  # noqa: E731
    assert check_tool(plan("답변 초안", "배송 조회"), "조회형")["tool"] == "배송 조회"        # 맞으면 그대로
    assert check_tool(plan("답변 초안", "FAQ 검색"), "접수형")["tool"] == "FAQ 검색"          # 초안의 FAQ 검색은 허용
    assert check_tool(plan("답변 초안", "배송 조회"), "접수형")["tool"] == "티켓 접수"
    assert check_tool(plan("자동 답변", "배송 조회"), "조회형")["tool"] == "FAQ 검색"
    assert check_tool(plan("담당자 연결", "티켓 접수"), "접수형")["tool"] == "상담원 이관"
    same = plan("답변 초안", "티켓 접수")
    assert check_tool(same, "접수형") is same


def _auto(ai):
    ai["llm"].replies = {"route": route_reply("자동 답변", "FAQ 검색", ["F05"]),
                         "answer": {"answer": "주문하신 맨투맨은 보통 1~3일 안에 도착합니다.", "used_faq_ids": ["F05"],
                                    "grounded": True}}


def test_auto_answer_mentions_verified_order_product(client, db, ai):
    _auto(ai)
    number = post(client, order_number="20261110-0001").json()["inquiry_number"]   # customer01 의 맨투맨 주문
    _, log = saved(db, number)
    assert "[확인된 주문] 상품: 맨투맨" in ai["llm"].inputs["answer"]
    assert log.tool_output["order_product"] == "맨투맨" and log.decision == "자동 답변"


def test_auto_answer_does_not_mention_unverified_order(client, db, ai):
    """주문번호가 다른 사람 것이면 상품을 알려 주지 않음 (자동 답변은 그대로, 담당자로 넘기지도 않음)"""
    _auto(ai)
    number = post(client, order_number="20261110-0001", customer_email="someone@example.com").json()["inquiry_number"]
    _, log = saved(db, number)
    assert "확인된 주문" not in ai["llm"].inputs["answer"]
    assert "order_product" not in log.tool_output and log.decision == "자동 답변"
