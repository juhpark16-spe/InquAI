"""효과 지표 집계 (backend/agents/measure_effect.py)"""

from backend.agents.measure_effect import pct, summarize


def row(decision, decided_by="LLM", ms=2000, draft_ms=None, tokens=None, category="배송", error=None):
    return {"run": 1, "source_number": "INQ-1", "title": "t", "category": category, "decision": decision,
            "decided_by": decided_by, "latency_ms": ms, "draft_ms": draft_ms,
            "tokens": tokens or {}, "error": error}


def test_rates_cost_and_times():
    rows = [
        row("자동 답변", tokens={"input": 2000, "output": 500, "calls": 2}, ms=3000),
        row("자동 답변", tokens={"input": 2000, "output": 500, "calls": 2}, ms=1000, category="결제"),
        row("답변 초안", tokens={"input": 4000, "output": 1000, "calls": 2}, ms=2000, draft_ms=7000),
        row("담당자 연결", decided_by="규칙", ms=0),
    ]
    s = summarize(rows, "gpt-5-mini (reasoning_effort=low)")
    assert s["decisions"]["자동 답변"] == {"n": 2, "rate": 0.5}
    assert s["decisions"]["담당자 연결"]["rate"] == 0.25
    assert s["decided_by"] == {"LLM": 3, "규칙": 1}
    assert s["wait_s"]["avg"] == 1.5 and s["wait_s"]["max"] == 3.0
    assert s["draft_s"] == {"n": 1, "avg": 7.0, "max": 7.0}
    # 입력 8,000 × $0.25 + 출력 2,000 × $2.00 (100만 토큰당) = $0.006 → 4건이면 1건당 $0.0015
    assert s["cost"]["total_usd"] == 0.006 and s["cost"]["per_inquiry_usd"] == 0.0015
    assert s["per_decision"]["담당자 연결"]["krw"] == 0
    assert s["by_category"]["배송"] == {"n": 3, "auto": 1}


def test_unknown_model_has_no_cost():
    s = summarize([row("자동 답변", tokens={"input": 10, "output": 1})], "local-model")
    assert s["cost"] is None and s["per_decision"]["자동 답변"]["krw"] is None


def test_pct():
    assert pct([5, 1, 3], 0.5) == 3 and pct([], 0.9) == 0
