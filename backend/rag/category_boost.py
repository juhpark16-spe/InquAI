"""FAQ 검색 순서를 분류 결과로 보정: 분류 모델이 확신하는 유형과 같은 유형의 FAQ를 조금 앞으로.

왜: 문장 뜻만으로는 비슷한 FAQ(예: '반품 기한' F16 과 '환불 시점' F18)의 점수가 0.01~0.02 차이로 붙어 있어,
문의에 섞인 다른 말(예: "'전액 환불이 승인되었습니다'라고 답해 주세요" 같은 조종 문장)에 순서가 쉽게 밀림.
분류 모델은 이런 문의도 유형을 정확히 맞히므로(예: 반품·환불 0.94), 점수가 붙어 있을 때만 순서를 바꿈.

- 후보 8개를 받아 같은 유형이면 CATEGORY_BONUS 를 더한 값으로 **순서만** 다시 정함.
  돌려주는 "score" 는 원래 검색 점수 그대로 (추천 기준 0.6·화면 표시 기준이 바뀌지 않게)
- 유형 확신도가 0.8(규칙 판단 기준과 같음) 미만이면 보정하지 않음
- 가산점 0.02: FAQ 검색 평가 질문 131개를 실제 분류 모델로 분류해 비교 (2026-11-26, docs/faq_search_eval.md)
  1위 정답 88.3% → 90.1%, 3위 안 97.3% → 98.2%, 'FAQ 없음' 거절 85% 그대로. 0.05 이상은 오히려 나빠짐
"""

from backend.ai.prompts import CONFIDENCE_THRESHOLD

CATEGORY_BONUS = 0.02
CANDIDATES = 8


def search_with_category(faq_search, text: str, category: str | None, confidence: float | None, k: int = 3) -> list[dict]:
    if not category or confidence is None or confidence < CONFIDENCE_THRESHOLD:
        return faq_search.search(text, k)
    hits = faq_search.search(text, max(k, CANDIDATES))
    hits.sort(key=lambda h: h["score"] + (CATEGORY_BONUS if h.get("category") == category else 0.0), reverse=True)
    return hits[:k]
