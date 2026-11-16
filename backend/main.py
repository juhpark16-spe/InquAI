"""InquAI FastAPI 서버.

실행 (프로젝트 루트에서)
    uvicorn backend.main:app --reload
API 문서: http://localhost:8000/docs
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import auth, faqs_public, health, inquiries, inquiry_admin, responses, staff, stats
from backend.core.config import get_settings
from backend.core.errors import register_error_handlers
from backend.core.security_headers import add_security_headers
from backend.database.session import SessionLocal, init_db
from backend.rag.faq_search import FaqSearch

settings = get_settings()
logger = logging.getLogger("inquai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # 테이블이 없으면 만듦
    with SessionLocal() as db:
        app.state.faq_search = FaqSearch.from_db(db)

    app.state.analyzer = None
    if settings.load_models:
        from backend.ai.classifier import Analyzer  # torch를 불러오는 데 시간이 걸려 필요할 때만

        app.state.analyzer = Analyzer(settings)  # 분류 모델 2개를 한 번만 불러와 메모리에 둠

    app.state.llm = None
    if settings.openai_api_key:
        from backend.ai.llm import LLM

        app.state.llm = LLM(settings)
    else:
        logger.warning("OPENAI_API_KEY 가 없어 LLM 판단 없이 동작합니다 (규칙에 걸리지 않는 문의는 검토 대기).")
    yield


app = FastAPI(title=f"{settings.app_name} API", version="0.2.0", lifespan=lifespan,
              description="쇼핑몰 고객 문의 자동 분석·처리 AI 에이전트",
              # 배포에서는 .env 의 API_DOCS=false 로 문서를 닫음
              docs_url="/docs" if settings.api_docs else None, redoc_url=None,
              openapi_url="/openapi.json" if settings.api_docs else None)
add_security_headers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,  # 로그인 쿠키를 주고받기 위해 필요
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(inquiries.router, prefix="/api")
app.include_router(inquiry_admin.router, prefix="/api")
app.include_router(responses.router, prefix="/api")
app.include_router(staff.router, prefix="/api")
app.include_router(faqs_public.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
