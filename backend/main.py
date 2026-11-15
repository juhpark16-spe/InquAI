"""InquAI FastAPI 서버.

실행 (프로젝트 루트에서)
    uvicorn backend.main:app --reload
API 문서: http://localhost:8000/docs
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import auth, health
from backend.core.config import get_settings
from backend.core.errors import register_error_handlers
from backend.database.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()  # 테이블이 없으면 만듦. 분류 모델 불러오기는 분석 API를 만들 때 여기에 추가
    yield


app = FastAPI(title=f"{settings.app_name} API", version="0.2.0", lifespan=lifespan,
              description="쇼핑몰 고객 문의 자동 분석·처리 AI 에이전트")

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
