"""FAQ 검색 (가벼운 대체용): 글자 2~4개 단위 TF-IDF. 기본은 KURE-v1 + ChromaDB (embedding_search.py)이고,
모델을 불러오지 않는 테스트나 KURE를 쓸 수 없을 때 이 검색을 씁니다.

1주차 프롬프트 검증(backend/ai/prompt_check.py)과 같은 방식이라 검증 결과를 그대로 기대할 수 있습니다.
FAQ가 바뀌면 FaqSearch 를 다시 만들어야 합니다 (FAQ 관리 API를 만들 때 연결).
"""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import Faq


class FaqSearch:
    engine = "tfidf"
    # 고객 화면 추천 기준값: 이 점수 이상인 FAQ만 추천 (평가: docs/faq_search_eval.md)
    suggest_min_score = 0.18
    def __init__(self, faqs: list[dict]):
        """faqs: [{"id": "F01", "category", "question", "answer"}] (id는 FAQ 번호)"""
        self.faqs = faqs
        self.vec = None
        if faqs:
            docs = [f"{f['question']} {f['question']} {f['answer']}" for f in faqs]  # 질문에 가중치
            self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit(docs)
            self.matrix = self.vec.transform(docs)

    @classmethod
    def from_db(cls, db: Session) -> "FaqSearch":
        rows = db.scalars(select(Faq).where(Faq.is_active.is_(True)).order_by(Faq.code)).all()
        return cls([{"id": f.code, "category": f.category, "question": f.question, "answer": f.answer} for f in rows])

    def search(self, text: str, k: int = 3) -> list[dict]:
        if self.vec is None:
            return []
        scores = cosine_similarity(self.vec.transform([text]), self.matrix)[0]
        return [{**self.faqs[i], "score": float(scores[i])} for i in scores.argsort()[::-1][:k]]
