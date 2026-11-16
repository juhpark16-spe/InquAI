"""FAQ 검색 평가 세트(data/test/faq_retrieval.json)와 계산 방법 확인"""

from collections import Counter

from backend.rag.evaluate_search import evaluate, load_cases, load_faqs

TYPES = {"바꿔 말하기", "구어체", "상황 설명", "여러 질문", "FAQ 없음"}


def test_case_file_is_consistent():
    faq_ids = {f["id"] for f in load_faqs()}
    cases = load_cases()
    assert len({c["id"] for c in cases}) == len(cases)            # 번호 중복 없음
    assert all(c["type"] in TYPES for c in cases)
    for c in cases:
        assert set(c["expected"]) <= faq_ids, c["id"]              # 없는 FAQ 번호를 정답으로 쓰지 않음
        assert bool(c["expected"]) == (c["type"] != "FAQ 없음"), c["id"]
    covered = Counter(e for c in cases for e in c["expected"])
    assert all(covered[f] >= 2 for f in faq_ids)                   # FAQ마다 2문장 이상
    assert sum(c["type"] == "FAQ 없음" for c in cases) >= 20


class FakeSearch:
    """문장별로 정해 둔 결과를 돌려주는 가짜 검색"""

    def __init__(self, answers):
        self.answers = answers

    def search(self, text, k=3):
        return [{"id": fid, "score": s} for fid, s in self.answers[text]][:k]


def test_metrics():
    cases = [
        {"id": "a", "type": "구어체", "text": "a", "expected": ["F01"]},             # 1위 정답
        {"id": "b", "type": "구어체", "text": "b", "expected": ["F02"]},             # 2위 정답
        {"id": "c", "type": "여러 질문", "match": "all", "text": "c", "expected": ["F01", "F03"]},  # 하나만 3위 안
        {"id": "d", "type": "FAQ 없음", "text": "d", "expected": []},               # 낮은 점수 → 걸러냄
        {"id": "e", "type": "FAQ 없음", "text": "e", "expected": []},               # 높은 점수 → 잘못 추천
    ]
    search = FakeSearch({
        "a": [("F01", 0.9), ("F02", 0.1)],
        "b": [("F05", 0.5), ("F02", 0.4)],
        "c": [("F01", 0.6), ("F09", 0.2)],
        "d": [("F07", 0.1)],
        "e": [("F07", 0.7)],
    })
    r = evaluate(search, cases, threshold=0.3)
    o = r["overall"]
    assert o["n"] == 3
    assert o["hit@1"] == round(2 / 3, 4)                 # a, c (1위가 정답 중 하나)
    assert o["hit@3"] == round(2 / 3, 4)                 # a, b (c는 F03이 없어 틀림)
    assert o["mrr"] == round((1 + 0.5 + 1) / 3, 4)
    cur = r["threshold"]["current"]
    assert cur["answer_ok"] == round(2 / 3, 4)           # a(0.9), c(0.6) 둘 다 0.3 이상
    assert cur["reject_ok"] == 0.5                       # d만 걸러냄
    assert [m["id"] for m in r["misses"]] == ["b"]
    assert [m["id"] for m in r["false_suggest"]] == ["e"]
    assert r["threshold"]["best"]["balanced"] >= cur["balanced"]
