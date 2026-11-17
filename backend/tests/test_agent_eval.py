"""에이전트 회귀 평가(evaluate_agent.py)의 채점 방법 확인 (OpenAI 없이)"""

import json
from pathlib import Path

from backend.agents.evaluate_agent import CASES, score, summarize
from backend.agents.pipeline import AgentResult


def case(**kw):
    base = {"id": "P", "text": "t", "expected_decision": ["자동 답변"], "expected_tool": ["FAQ 검색"],
            "expected_faqs": [], "point": ""}
    return {**base, **kw}


def test_cases_file_is_valid():
    cases = json.loads(Path(CASES).read_text(encoding="utf-8"))
    assert len({c["id"] for c in cases}) == len(cases) >= 20
    for c in cases:
        assert set(c["expected_decision"]) <= {"자동 답변", "답변 초안", "담당자 연결"}
        assert set(c["expected_tool"]) <= {"FAQ 검색", "배송 조회", "티켓 접수", "상담원 이관"}


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
