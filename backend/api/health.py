"""서버 상태 확인: GET /api/health (공개)."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.database.models import AdminUser, Faq, Order
from backend.database.session import get_db

router = APIRouter(tags=["상태"])


@router.get("/health", summary="서버·DB 상태")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    settings = get_settings()
    count = lambda model: db.scalar(select(func.count()).select_from(model))  # noqa: E731
    return {
        "status": "ok",
        "database": settings.resolved_database_url.split(":", 1)[0],
        "seed": {"admin_users": count(AdminUser), "faqs": count(Faq), "orders": count(Order)},
        "models_ready": settings.category_model_dir.exists() and settings.sentiment_model_dir.exists(),
    }
