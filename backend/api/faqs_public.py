"""고객용 FAQ API (공개): FAQ 목록, 문의 작성 중 비슷한 FAQ 추천.

관리자용 FAQ 관리(등록·수정·비활성)는 /api/faqs (docs/api_spec.md 8장)로 따로 만듭니다.
"""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from backend.core.dependencies import DB
from backend.core.rate_limit import rate_limit
from backend.database.models import Faq

router = APIRouter(prefix="/public/faqs", tags=["고객 FAQ"])

# 추천에 띄울 최소 유사도 (임시 TF-IDF 기준. 맞는 FAQ는 보통 0.2 이상, "이 옷 이쁜가요?" 같은
# 관계없는 문장도 0.15까지 나와서 0.18로 둠. 3주차에 임베딩 검색으로 바꾸면 다시 정함)
SUGGEST_MIN_SCORE = 0.18


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
    hits = [f for f in search.search(q, k) if f["score"] >= SUGGEST_MIN_SCORE]
    return [{"code": f["id"], "category": f["category"], "question": f["question"], "answer": f["answer"]} for f in hits]
