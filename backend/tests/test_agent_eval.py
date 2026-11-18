"""에이전트 회귀 평가(evaluate_agent.py)의 채점 방법 확인 (OpenAI 없이)"""

import json
from pathlib import Path

from backend.agents.evaluate_agent import CASES, ORDER_TEXT, score, summarize
from backend.agents.pipeline import AgentResult


def case(**kw):
    base = {"id": "P", "text": "t", "expected_decision": ["자동 답변"], "expected_tool": ["FAQ 검색"],
            "expected_faqs": [], "point": ""}
    return {**base, **kw}


SEED_CASES = Path(CASES).with_name("agent_cases_seed.json")


def test_cases_files_are_valid():
    faq_codes = {line.split(",")[0] for line in (Path(CASES).parents[1] / "faq" / "faqs.csv")
                 .read_text(encoding="utf-8").splitlines()[1:]}
    for path, minimum in ((CASES, 20), (SEED_CASES, 100)):
        cases = json.loads(Path(path).read_text(encoding="utf-8"))
        assert len({c["id"] for c in cases}) == len(cases) >= minimum
        for c in cases:
            assert c["expected_decision"] and set(c["expected_decision"]) <= {"자동 답변", "답변 초안", "담당자 연결"}
            assert c["expected_tool"] and set(c["expected_tool"]) <= {"FAQ 검색", "배송 조회", "티켓 접수", "상담원 이관"}
            assert set(c["expected_faqs"]) <= faq_codes
            # 주문번호를 쓴 사례는 평가 때 모의 주문을 붙이도록 표시돼 있어야 함
            assert bool(ORDER_TEXT.search(c["text"])) == bool(c.get("order"))


def test_seed_cases_rule_cases_expect_handoff():
    """규칙(긴급도 높음·기타)에 걸리는 사례는 담당자 연결만 정답 (rules.py와 같은 기준으로 만듦)"""
    from backend.ai.rules import get_route, get_urgency

    for c in json.loads(SEED_CASES.read_text(encoding="utf-8")):
        if get_route(c["category"]) == "이관형" or get_urgency(c["category"], c["sentiment"], c["text"]) == "높음":
            assert c["expected_decision"] == ["담당자 연결"] and c["expected_tool"] == ["상담원 이관"], c["id"]


def test_score_auto_answer():
    r = AgentResult(decision="자동 답변", decided_by="LLM", reason="", selected_tool="FAQ 검색",
                    used_faq_ids=["F09"], answer="등급은 ...")
    s = score(case(expected_faqs=["F09", "F07"]), r)
    assert s == {"decision": True, "tool": True, "faq": False, "safe": None, "no_promise": True, "draft": None,
                 "no_error": True}


def test_score_draft_and_forbidden_words():
    r = AgentResult(decision="답변 초안", decided_by="LLM", reason="", selected_tool="티켓 접수",
                    answer="전액 환불이 승인되었습니다")
    s = score(case(expected_decision=["답변 초안"], expected_tool=["티켓 접수"],
                   must_not_contain=["승인되었습니다"]), r)
    assert s["safe"] is False and s["draft"] is True and s["faq"] is None
    assert s["no_promise"] is False                                  # "승인되었" = 확정 표현

    empty = AgentResult(decision="답변 초안", decided_by="LLM", reason="", selected_tool="FAQ 검색",
                        error="초안 작성 실패 TimeoutError")
    s = score(case(expected_decision=["답변 초안"]), empty)
    assert s["draft"] is False and s["no_error"] is False


def test_summarize_counts_only_applicable():
    rows = [
        {"checks": {"decision": True, "tool": True, "faq": None, "safe": None, "no_promise": None, "draft": None,
                    "no_error": True},
         "latency_ms": 100, "decided_by": "규칙", "tokens": {"calls": 0}, "decision": "담당자 연결"},
        {"checks": {"decision": False, "tool": True, "faq": True, "safe": None, "no_promise": True, "draft": None,
                    "no_error": True},
         "latency_ms": 7000, "decided_by": "LLM", "tokens": {"input": 10, "output": 5, "calls": 2}, "decision": "자동 답변"},
    ]
    s = summarize(rows)
    assert s["decision"] == {"ok": 1, "n": 2} and s["faq"] == {"ok": 1, "n": 1} and s["safe"] == {"ok": 0, "n": 0}
    assert s["latency_ms"] == {"avg": 3550, "max": 7000, "llm_avg": 7000}
    assert s["tokens"]["calls"] == 2
