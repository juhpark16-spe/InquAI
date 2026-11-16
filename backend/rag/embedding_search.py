"""FAQ 검색 (3주차): KURE-v1 임베딩 + ChromaDB.

- 모델: nlpai-lab/KURE-v1 (BAAI/bge-m3를 한국어로 추가 학습, MIT 라이선스, 약 2.3GB).
  문장을 1024차원 벡터로 바꿔 '뜻'이 가까운 FAQ를 찾습니다 (글자가 달라도 됨).
- 저장소: ChromaDB (data/chroma/). FAQ 벡터를 저장해 두고, FAQ 내용이 바뀌었을 때만 다시 계산합니다.
- 점수: 코사인 유사도 (1 = 같은 뜻, 0 = 관계없음). TF-IDF 점수와 범위가 달라 추천 기준값을 따로 정합니다
  (docs/faq_search_eval.md).

TF-IDF 검색(faq_search.py)과 같은 모양(search(text, k) → [{id, category, question, answer, score}])이라
에이전트·고객 추천 API는 바꾸지 않아도 됩니다.
"""

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger("inquai")

MODEL_NAME = "nlpai-lab/KURE-v1"
CHROMA_DIR = Path(__file__).resolve().parents[2] / "data" / "chroma"
COLLECTION = "faqs"


def faq_document(f: dict, mode: str = "qa") -> str:
    """FAQ 한 개를 벡터로 바꿀 글. qa: 질문 + 답변 (평가에서 더 정확해 기본값) / question: 질문만"""
    return f["question"] if mode == "question" else f"{f['question']}\n{f['answer']}"


def load_model(name: str = MODEL_NAME, device: str | None = None):
    from sentence_transformers import SentenceTransformer
    import torch

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    return SentenceTransformer(name, device=device)


class KureFaqSearch:
    engine = "kure"
    # 고객 화면 추천 기준값: 평가 세트에서 추천 정확도·걸러냄 평균이 가장 높은 값 (docs/faq_search_eval.md)
    suggest_min_score = 0.6
    def __init__(self, faqs: list[dict], model, *, doc_mode: str = "qa", persist_dir: Path | None = CHROMA_DIR):
        """faqs: [{"id": "F01", "category", "question", "answer"}]. persist_dir=None 이면 메모리에만 (테스트·평가용)"""
        import chromadb

        self.faqs = faqs
        self.model = model
        self.doc_mode = doc_mode
        self.by_id = {f["id"]: f for f in faqs}
        client = chromadb.PersistentClient(path=str(persist_dir)) if persist_dir else chromadb.EphemeralClient()
        # FAQ 내용 + 모델 + 문서 방식이 같으면 저장된 벡터를 그대로 씀
        digest = hashlib.sha256(json.dumps([faqs, MODEL_NAME, doc_mode], ensure_ascii=False,
                                           sort_keys=True).encode()).hexdigest()[:16]
        name = f"{COLLECTION}_{doc_mode}"
        col = client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})
        if (col.metadata or {}).get("digest") != digest or col.count() != len(faqs):
            client.delete_collection(name)
            col = client.create_collection(name, metadata={"hnsw:space": "cosine", "digest": digest})
            if faqs:
                vectors = self._encode([faq_document(f, doc_mode) for f in faqs])
                col.add(ids=[f["id"] for f in faqs], embeddings=vectors,
                        metadatas=[{"category": f["category"]} for f in faqs])
            logger.info("FAQ 벡터 %d개 저장 (ChromaDB %s)", len(faqs), name)
        self.collection = col

    def _encode(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True).tolist()

    @classmethod
    def from_db(cls, db, model, **kwargs) -> "KureFaqSearch":
        from sqlalchemy import select

        from backend.database.models import Faq

        rows = db.scalars(select(Faq).where(Faq.is_active.is_(True)).order_by(Faq.code)).all()
        faqs = [{"id": f.code, "category": f.category, "question": f.question, "answer": f.answer} for f in rows]
        return cls(faqs, model, **kwargs)

    def search(self, text: str, k: int = 3) -> list[dict]:
        if not self.faqs or not text.strip():
            return []
        r = self.collection.query(query_embeddings=self._encode([text]), n_results=min(k, len(self.faqs)))
        return [{**self.by_id[fid], "score": round(1 - dist, 4)} for fid, dist in zip(r["ids"][0], r["distances"][0])]
