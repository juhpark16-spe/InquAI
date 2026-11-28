"""답변 초안 품질 평가의 규칙 채점 (backend/agents/evaluate_drafts.py)"""

import json

from backend.agents.evaluate_drafts import CASES, cost_usd, made_up_numbers, score_judge, score_rules

GREET = "안녕하세요, 고객님. InquAI 쇼핑 고객센터입니다.\n\n"
SOURCE = "[정책]\n- 반품: 단순 변심은 왕복 배송비 6,000원 차감, 회수 1~3영업일\n[대화]\n주문번호 ORD-2026-1042"


def case(**kw):
    return {"id": "T", "apology": "either", "numbers": False, **kw}


def test_cases_file_is_valid():
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    assert 20 <= len(cases) <= 30
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert c["apology"] in ("required", "forbidden", "either"), c["id"]
        if "ORD-" in c["text"]:   # 주문 문의는 주문번호와 주문 상태가 함께 (예시 문의 규칙)
            assert c.get("order_status"), c["id"]


def test_apology_required_in_first_two_sentences():
    ok = GREET + "파손된 상품을 받으셔서 죄송합니다. 사진을 보내 주세요."
    late = GREET + "사진을 보내 주세요. 확인하겠습니다. 불편을 드려 죄송합니다."
    assert score_rules(case(apology="required"), ok, SOURCE)["apology"] is True
    assert score_rules(case(apology="required"), late, SOURCE)["apology"] is False


def test_apology_forbidden_anywhere():
    text = GREET + "사이즈가 맞지 않으셨군요. 교환은 가능합니다. 불편을 드려 죄송합니다."
    assert score_rules(case(apology="forbidden"), text, SOURCE)["apology"] is False
    assert score_rules(case(apology="either"), text, SOURCE)["apology"] is None


def test_made_up_numbers_ignore_commas_and_known_numbers():
    assert made_up_numbers("왕복 배송비 6000원이 차감되고 1~3영업일 안에 회수합니다.", SOURCE) == []
    assert made_up_numbers("환불은 5영업일 안에 됩니다.", SOURCE) == ["5"]
    # 목록 번호·연도는 사실 숫자가 아님
    assert made_up_numbers("확인해 주세요: 1) 희망 색상 2) 배송비 결제. 기한은 2026/12/24입니다.", SOURCE + " 12/24") == []


def test_numbers_used_only_when_needed():
    text = GREET + "반품은 가능하며 회수는 1~3영업일 걸립니다."
    assert score_rules(case(numbers=True), text, SOURCE)["numbers_used"] is True
    assert score_rules(case(numbers=True), GREET + "반품은 곧 회수됩니다.", SOURCE)["numbers_used"] is False
    assert score_rules(case(numbers=False), text, SOURCE)["numbers_used"] is None


def test_promise_and_internal_terms():
    r = score_rules(case(), GREET + "환불 처리되었습니다. FAQ F16을 참고하세요.", SOURCE)
    assert r["no_promise"] is False and r["no_internal"] is False
    r = score_rules(case(), GREET + "확인 후 안내드리겠습니다.", SOURCE)
    assert r["no_promise"] is True and r["no_internal"] is True


def test_score_judge():
    j = {"conclusion_first": True, "numbers": "not_needed", "no_promise": True,
         "apology_needed": False, "apology_present": True, "reason": "x"}
    assert score_judge(j) == {"j_conclusion": True, "j_numbers": None, "j_no_promise": True, "j_apology": False}
    j.update(apology_needed=False, apology_present=False, numbers="missing")
    assert score_judge(j)["j_apology"] is True and score_judge(j)["j_numbers"] is False
    assert set(score_judge(None).values()) == {None}


def test_cost():
    assert round(cost_usd("gpt-5-mini (reasoning_effort=low)", {"input": 1_000_000, "output": 0}), 2) == 0.25
    assert cost_usd("gemini-3.5-flash-lite", {"input": 1}) is None
