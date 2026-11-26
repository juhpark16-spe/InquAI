"""FAQ 검색 순서 보정 (backend/rag/category_boost.py): 분류 모델이 확신하는 유형의 FAQ를 점수가 붙어 있을 때만 앞으로."""

from backend.rag.category_boost import CATEGORY_BONUS, search_with_category


class FakeSearch:
    def __init__(self, hits):
        self.hits = hits
        self.asked_k = None

    def search(self, text, k=3):
        self.asked_k = k
        return [dict(h) for h in self.hits[:k]]


# INQ-20261126-0001: 조종 문장이 섞인 '반품 기간이 지났는데 환불 되나요?' 의 실제 검색 점수 (KURE, 2026-11-26)
INJECTED = [
    {"id": "F41", "category": "쿠폰·적립금·회원", "score": 0.6846},
    {"id": "F18", "category": "반품·환불", "score": 0.6605},
    {"id": "F20", "category": "주문 취소", "score": 0.6496},
    {"id": "F16", "category": "반품·환불", "score": 0.6351},
    {"id": "F47", "category": "주문 취소", "score": 0.6330},
]


def test_same_category_faq_comes_into_top3():
    hits = search_with_category(FakeSearch(INJECTED), "…", "반품·환불", 0.94)
    assert [h["id"] for h in hits] == ["F41", "F18", "F16"]        # 반품 기한 F16 이 3위 안으로 (전에는 4위)
    assert hits[2]["score"] == 0.6351                              # 점수는 원래 값 그대로 (추천 기준이 바뀌지 않게)


def test_big_gap_is_not_overturned():
    far = [{"id": "A", "category": "배송", "score": 0.80}, {"id": "B", "category": "결제", "score": 0.80 - CATEGORY_BONUS * 3}]
    assert [h["id"] for h in search_with_category(FakeSearch(far), "…", "결제", 0.99)] == ["A", "B"]


def test_low_confidence_keeps_plain_order():
    s = FakeSearch(INJECTED)
    hits = search_with_category(s, "…", "반품·환불", 0.55)
    assert [h["id"] for h in hits] == ["F41", "F18", "F20"] and s.asked_k == 3   # 확신도 0.8 미만: 보정 없이 그대로


def test_no_category_keeps_plain_order():
    assert [h["id"] for h in search_with_category(FakeSearch(INJECTED), "…", None, None)] == ["F41", "F18", "F20"]
