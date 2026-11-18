"""FAQ 관리 API (관리자만, docs/api_spec.md 8장).

    GET    /api/faqs                 목록 (category, q, include_inactive) + AI가 근거로 쓴 횟수
    POST   /api/faqs                 등록 (번호를 비우면 다음 번호)
    PUT    /api/faqs/{id}            수정 (유형·질문·답변·활성 여부)
    DELETE /api/faqs/{id}            비활성 (실제로 지우지 않음: 지난 답변의 근거 FAQ 번호가 남아 있기 때문)
    GET    /api/faqs/search-test?q=  이 질문이면 어떤 FAQ가 검색되는지 (에이전트·고객 추천과 같은 검색)

등록·수정·비활성 뒤에는 검색 색인(KURE + ChromaDB)을 바로 다시 만듭니다.
"""

from fastapi import APIRouter, Query, Request
from sqlalchemy import or_, select

from backend.core.dependencies import DB, AdminOnly
from backend.core.errors import AppError
from backend.database.models import Faq
from backend.schemas.faqs import FaqAdmin, FaqCreate, FaqUpdate, SearchTest
from backend.services.audit import add_audit
from backend.services.faqs import next_code, refresh_search, usage

router = APIRouter(prefix="/faqs", tags=["FAQ 관리"])
FIELDS = ("category", "question", "answer", "is_active")


def _out(f: Faq, used: dict) -> dict:
    n, last = used.get(f.code, (0, None))
    return {**{k: getattr(f, k) for k in ("id", "code", "category", "question", "answer", "is_active",
                                          "created_at", "updated_at")},
            "used_count": n, "last_used_at": last}


def _get(db, faq_id: int) -> Faq:
    faq = db.get(Faq, faq_id)
    if faq is None:
        raise AppError(404, "FAQ를 찾을 수 없습니다.", "NOT_FOUND")
    return faq


@router.get("", response_model=list[FaqAdmin], summary="FAQ 목록 (관리자)")
def list_faqs(_: AdminOnly, db: DB, category: str | None = None, q: str | None = Query(None, max_length=100),
              include_inactive: bool = True):
    stmt = select(Faq).order_by(Faq.is_active.desc(), Faq.code)
    if category:
        stmt = stmt.where(Faq.category == category)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Faq.code.ilike(like), Faq.question.ilike(like), Faq.answer.ilike(like)))
    if not include_inactive:
        stmt = stmt.where(Faq.is_active.is_(True))
    used = usage(db)
    return [_out(f, used) for f in db.scalars(stmt).all()]


@router.get("/search-test", response_model=SearchTest, summary="FAQ 검색 미리 보기 (관리자)")
def search_test(request: Request, _: AdminOnly, q: str = Query(min_length=2, max_length=500),
                k: int = Query(3, ge=1, le=5)):
    search = getattr(request.app.state, "faq_search", None)
    if search is None:
        return {"engine": None, "suggest_min_score": None, "hits": []}
    hits = [{"code": h["id"], "category": h["category"], "question": h["question"], "score": round(h["score"], 4),
             "suggested": h["score"] >= search.suggest_min_score} for h in search.search(q, k)]
    return {"engine": search.engine, "suggest_min_score": search.suggest_min_score, "hits": hits}


@router.post("", response_model=FaqAdmin, status_code=201, summary="FAQ 등록 (관리자)")
def create_faq(body: FaqCreate, request: Request, admin: AdminOnly, db: DB):
    code = body.code or next_code(db)
    if db.scalar(select(Faq).where(Faq.code == code)):
        raise AppError(409, f"이미 있는 FAQ 번호입니다: {code}", "FAQ_CODE_TAKEN")
    faq = Faq(code=code, category=body.category, question=body.question, answer=body.answer, is_active=True)
    db.add(faq)
    db.flush()
    add_audit(db, request, "faq_create", admin, "faq", faq.id,
              after={"code": code, **body.model_dump(exclude={"code"})})
    db.commit()
    refresh_search(request.app.state, db)
    return _out(faq, usage(db))


@router.put("/{faq_id}", response_model=FaqAdmin, summary="FAQ 수정 (관리자)")
def update_faq(faq_id: int, body: FaqUpdate, request: Request, admin: AdminOnly, db: DB):
    faq = _get(db, faq_id)
    after = body.model_dump()
    before = {k: getattr(faq, k) for k in FIELDS}
    changed = {k: v for k, v in after.items() if before[k] != v}
    if changed:
        for k, v in changed.items():
            setattr(faq, k, v)
        action = "faq_deactivate" if changed == {"is_active": False} else "faq_update"
        add_audit(db, request, action, admin, "faq", faq.id, code=faq.code,
                  before={k: before[k] for k in changed}, after=changed)
        db.commit()
        refresh_search(request.app.state, db)
    return _out(faq, usage(db))


@router.delete("/{faq_id}", response_model=FaqAdmin, summary="FAQ 비활성 (관리자)")
def deactivate_faq(faq_id: int, request: Request, admin: AdminOnly, db: DB):
    faq = _get(db, faq_id)
    if faq.is_active:
        faq.is_active = False
        add_audit(db, request, "faq_deactivate", admin, "faq", faq.id, code=faq.code)
        db.commit()
        refresh_search(request.app.state, db)
    return _out(faq, usage(db))
