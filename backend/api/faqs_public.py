"""고객용 FAQ API (공개): FAQ 목록, 문의 작성 중 비슷한 FAQ 추천.

관리자용 FAQ 관리(등록·수정·비활성)는 /api/faqs (faqs_admin.py, docs/api_spec.md 8장).
"""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from backend.core.dependencies import DB
from backend.core.rate_limit import rate_limit
from backend.database.models import Faq

router = APIRouter(prefix="/public/faqs", tags=["고객 FAQ"])

# 추천에 띄울 최소 유사도는 검색 방식마다 점수 범위가 달라 검색 객체가 정합니다
# (KURE 0.6, TF-IDF 0.18 — 평가 세트로 정한 값, docs/faq_search_eval.md)


class FaqPublic(BaseModel):
    code: str
    category: str
    question: str
    answer: str


@router.get("", response_model=list[FaqPublic], summary="FAQ 목록 (공개, 활성 FAQ만)")
def list_faqs(db: DB):
    rows = db.scalars(select(Faq).where(Faq.is_active.is_(True)).order_by(Faq.code)).all()
    return [{"code": f.code, "category": f.category, "question": f.question, "answer": f.answer} for f in rows]


@router.get("/suggest", response_model=list[FaqPublic], summary="비슷한 FAQ 추천 (문의 작성 중)",
            dependencies=[Depends(rate_limit("faq_suggest", 30, 60))])
def suggest_faqs(request: Request, q: str = Query(min_length=2, max_length=2000), k: int = Query(3, ge=1, le=5)):
    search = getattr(request.app.state, "faq_search", None)
    if search is None:
        return []
    hits = [f for f in search.search(q, k) if f["score"] >= search.suggest_min_score]
    return [{"code": f["id"], "category": f["category"], "question": f["question"], "answer": f["answer"]} for f in hits]
