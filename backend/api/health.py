"""서버 상태 확인: GET /api/health (공개)."""

from fastapi import APIRouter, Request
from sqlalchemy import func, select, text

from backend.core.config import get_settings
from backend.core.dependencies import DB
from backend.database.models import AdminUser, Faq, Order

router = APIRouter(tags=["상태"])


@router.get("/health", summary="서버·DB·AI 준비 상태")
def health(request: Request, db: DB):
    db.execute(text("SELECT 1"))
    count = lambda model: db.scalar(select(func.count()).select_from(model))  # noqa: E731
    state = request.app.state
    return {
        "status": "ok",
        "database": get_settings().resolved_database_url.split(":", 1)[0],
        "seed": {"admin_users": count(AdminUser), "faqs": count(Faq), "orders": count(Order)},
        "ai": {"classifier": getattr(state, "analyzer", None) is not None,
               "llm": getattr(state, "llm", None) is not None,
               "faqs_indexed": len(getattr(state, "faq_search", None).faqs) if getattr(state, "faq_search", None) else 0,
               "faq_engine": getattr(getattr(state, "faq_search", None), "engine", None)},
    }
