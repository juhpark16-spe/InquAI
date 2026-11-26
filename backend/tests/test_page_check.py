"""표기 재확인: 상품 페이지 표기 오류 신호가 있는 문의만 LLM이 유형을 다시 정함 (backend/ai/page_check.py)"""

from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import select

from backend.ai.page_check import has_page_signal
from backend.database.models import AnalysisResult
from backend.tests.test_inquiries import FakeAnalyzer, ai, post, route_reply, saved  # noqa: F401  (fixture 재사용)

EVAL = Path(__file__).resolve().parents[2] / "data" / "test" / "page_error_eval.csv"
NOTICE = "옵션에는 6개입이라고 되어 있는데 상세 이미지에는 4개입이라고 나와요."


def test_signal_catches_every_page_error_sentence():
    d = pd.read_csv(EVAL)
    notices = d[d["note"].str.startswith(("표기 오류", "페이지 오류"))]["text"]
    assert len(notices) == 15
    assert [t for t in notices if not has_page_signal(t)] == []


@pytest.mark.parametrize("text", [
    "배송은 보통 며칠 걸려요?", "M 사이즈 입으면 맞을까요?", "6개월 이상 사용하면 고장 나나요?",
    "쿠폰이 적용이 안 돼요", "주문 취소하고 싶어요", "환불은 언제 들어오나요?",
])
def test_signal_ignores_ordinary_inquiries(text):
    assert not has_page_signal(text)


class ProductAnalyzer(FakeAnalyzer):
    """분류 모델이 표기 오류 알림을 '상품'으로 잘못 본 상황"""

    def analyze(self, text):
        a = super().analyze(text)
        return {**a, "category": "상품", "confidence": 0.93, "route": "FAQ형", "urgency": "낮음",
                "scores": {"category": {"상품": 0.93, "기타": 0.05, "교환": 0.02}}}


@pytest.fixture()
def product(ai):
    from backend.main import app
    app.state.analyzer = ProductAnalyzer()
    return ai


def analysis_of(db, number):
    inquiry, log = saved(db, number)
    return inquiry, log, db.scalar(select(AnalysisResult).where(AnalysisResult.inquiry_id == inquiry.id))


def test_llm_moves_page_error_to_other_and_staff(client, db, product):
    product["llm"].replies = {"category": {"category": "기타"}}
    inquiry, log, a = analysis_of(db, post(client, content=NOTICE).json()["inquiry_number"])
    assert a.category == "기타" and a.route == "이관형" and a.confidence == pytest.approx(0.05)
    assert a.scores["page_recheck"] == {"model": "상품", "llm": "기타", "changed": True}
    assert a.scores["category"]["상품"] == 0.93                   # 분류 모델 점수는 그대로 남김
    assert log.category == "기타" and log.steps[0] == "표기 재확인"
    assert inquiry.status == "담당자 처리"
    assert product["llm"].calls == ["category"]                   # 기타 → 규칙으로 사람에게 (처리 방식 LLM 판단 없음)
    assert log.tokens["calls"] == 1 and log.tokens["input"] == 100


def test_llm_agrees_keeps_model_result(client, db, product):
    product["llm"].replies = {"category": {"category": "상품"}, "route": route_reply("답변 초안", "FAQ 검색"),
                              "draft": {"answer": "확인 후 안내드리겠습니다.", "used_faq_ids": [], "grounded": False,
                                        "check_points": []}}
    _, log, a = analysis_of(db, post(client, content=NOTICE).json()["inquiry_number"])
    assert a.category == "상품" and a.confidence == 0.93
    assert a.scores["page_recheck"]["changed"] is False
    assert product["llm"].calls[:2] == ["category", "route"]


def test_llm_failure_falls_back_to_model(client, db, product):
    product["llm"].replies = {"category": TimeoutError("느림"), "route": route_reply("답변 초안", "FAQ 검색"),
                              "draft": {"answer": "확인 후 안내드리겠습니다.", "used_faq_ids": [], "grounded": False,
                                        "check_points": []}}
    _, log, a = analysis_of(db, post(client, content=NOTICE).json()["inquiry_number"])
    assert a.category == "상품" and log.steps[0] == "표기 재확인(실패)"
    assert a.scores["page_recheck"]["llm"] is None and "TimeoutError" in a.scores["page_recheck"]["error"]
    assert log.error is None                                       # 재확인 실패는 처리 실패가 아님


def test_unknown_category_falls_back(client, db, product):
    product["llm"].replies = {"category": {"category": "없는 유형"}, "route": route_reply("답변 초안", "FAQ 검색"),
                              "draft": {"answer": "확인 후 안내드리겠습니다.", "used_faq_ids": [], "grounded": False,
                                        "check_points": []}}
    _, log, a = analysis_of(db, post(client, content=NOTICE).json()["inquiry_number"])
    assert a.category == "상품" and log.steps[0] == "표기 재확인(실패)"


def test_no_signal_no_llm_call(client, db, product):
    product["llm"].replies = {"route": route_reply("답변 초안", "FAQ 검색"),
                              "draft": {"answer": "확인 후 안내드리겠습니다.", "used_faq_ids": [], "grounded": False,
                                        "check_points": []}}
    _, log, a = analysis_of(db, post(client, content="이 텀블러 보온은 몇 시간 되나요?").json()["inquiry_number"])
    assert "category" not in product["llm"].calls and "page_recheck" not in a.scores
    assert "표기 재확인" not in log.steps


def test_change_outside_boundary_is_ignored():
    """상품·기타와 상관없는 바꿈(회원 → 교환)은 LLM의 흔들림으로 보고 무시"""
    from backend.ai.page_check import apply_recheck
    a = {"category": "쿠폰·적립금·회원", "confidence": 0.97, "sentiment": "중립", "route": "FAQ형", "urgency": "낮음",
         "scores": {"category": {"쿠폰·적립금·회원": 0.97, "교환": 0.01}}}
    new = apply_recheck(a, "5번 틀렸더니 계정이 잠겼다고 나와요", "교환")
    assert new["category"] == "쿠폰·적립금·회원" and new["confidence"] == 0.97
    assert new["scores"]["page_recheck"] == {"model": "쿠폰·적립금·회원", "llm": "교환", "changed": False, "ignored": True}
    moved = apply_recheck(a, "마이페이지 이름이 틀리게 나와요", "기타")   # 기타로 가면 사람에게 (안전한 쪽)
    assert moved["category"] == "기타" and moved["route"] == "이관형"
