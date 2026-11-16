"""KURE + ChromaDB FAQ 검색: 진짜 모델(2.3GB) 대신 단어로 벡터를 만드는 가짜 모델로 동작만 확인"""

import numpy as np

from backend.rag.embedding_search import KureFaqSearch

WORDS = ["배송", "환불", "쿠폰", "비밀번호", "교환"]
FAQS = [
    {"id": "F01", "category": "배송", "question": "배송은 얼마나 걸리나요?", "answer": "보통 배송 1~2일"},
    {"id": "F02", "category": "반품·환불", "question": "환불은 언제 되나요?", "answer": "환불 3영업일"},
    {"id": "F03", "category": "쿠폰·적립금·회원", "question": "쿠폰이 안 돼요", "answer": "쿠폰 조건 확인"},
]


class FakeModel:
    """글에 들어 있는 단어로 벡터를 만듦 (뜻 대신 단어, 계산 방식만 확인용)"""

    def __init__(self):
        self.calls = 0

    def encode(self, texts, normalize_embeddings=True, convert_to_numpy=True):
        self.calls += 1
        v = np.array([[t.count(w) + 0.01 for w in WORDS] for t in texts], dtype=float)
        return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_search_returns_closest_faq_with_cosine_score():
    s = KureFaqSearch(FAQS, FakeModel(), persist_dir=None)
    hits = s.search("환불 언제 들어와요", k=2)
    assert [h["id"] for h in hits][0] == "F02"
    assert hits[0]["score"] > hits[1]["score"] and 0 < hits[0]["score"] <= 1
    assert {"id", "category", "question", "answer", "score"} <= set(hits[0])
    assert s.search("   ") == []


def test_vectors_are_reused_until_faqs_change(tmp_path):
    m = FakeModel()
    KureFaqSearch(FAQS, m, persist_dir=tmp_path)
    assert m.calls == 1                                   # 처음: FAQ 벡터 계산
    KureFaqSearch(FAQS, m, persist_dir=tmp_path)
    assert m.calls == 1                                   # 같은 FAQ: 저장된 벡터 그대로
    changed = [*FAQS[:2], {**FAQS[2], "answer": "쿠폰 최소 주문 금액 확인"}]
    s = KureFaqSearch(changed, m, persist_dir=tmp_path)
    assert m.calls == 2                                   # FAQ가 바뀜: 다시 계산
    assert s.collection.count() == 3


def test_suggest_uses_threshold_of_search_engine(client):
    class Strict:
        engine, suggest_min_score, faqs = "fake", 0.6, FAQS

        def search(self, text, k=3):
            return [{**FAQS[0], "score": 0.7}, {**FAQS[1], "score": 0.5}][:k]

    client.app.state.faq_search = Strict()
    r = client.get("/api/public/faqs/suggest", params={"q": "배송 문의"})
    assert [f["code"] for f in r.json()] == ["F01"]       # 0.5는 기준값 0.6 미만이라 빠짐
