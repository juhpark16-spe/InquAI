"""서버 설정. 값은 프로젝트 루트의 .env 에서 읽습니다 (항목 설명은 .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "InquAI"
    database_url: str = "sqlite:///./data/inquai.db"

    # OpenAI (추론 강도 low: 1주차 프롬프트 검증에서 정확도·속도 균형이 가장 좋았음)
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    llm_reasoning_effort: str = "low"
    # 문의 등록 1건의 에이전트 처리 제한 시간. 넘으면 자동 답변 없이 '검토 대기' (docs/api_spec.md 3장)
    agent_timeout_seconds: float = 20.0

    # 로그인 (기획서 6장, docs/api_spec.md 1장)
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    cookie_secure: bool = True
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    # 관리자·상담원 비밀번호 최소 길이. 기본 8자, 시연용 로컬 환경에서만 .env 로 낮춤 (예: 4 → "1234")
    password_min_length: int = 8

    # API 문서(/docs, /openapi.json) 공개 여부. 배포에서는 false (공격자에게 API 목록을 보여주지 않게)
    api_docs: bool = True

    # CORS: 쉼표로 여러 주소
    frontend_origins: str = "http://localhost:5173"

    # 분류 모델 폴더와 버전 이름 (docs/model_card.md). 테스트에서는 load_models=false 로 불러오지 않음
    load_models: bool = True
    category_model_dir: Path = PROJECT_ROOT / "models" / "category_classifier"
    sentiment_model_dir: Path = PROJECT_ROOT / "models" / "sentiment_classifier"
    category_model_version: str = "category_ev_s123"
    sentiment_model_version: str = "sentiment_v1"

    # 초기 계정 비밀번호 (seed_admin.py)
    seed_admin_password: str = ""
    seed_agent_password: str = ""

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_origins.split(",") if o.strip()]

    @property
    def resolved_database_url(self) -> str:
        """SQLite 상대 경로는 실행 위치와 상관없이 프로젝트 루트 기준으로 바꿉니다."""
        prefix = "sqlite:///./"
        if self.database_url.startswith(prefix):
            return f"sqlite:///{(PROJECT_ROOT / self.database_url[len(prefix):]).as_posix()}"
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
