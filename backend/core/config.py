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

    # LangSmith 추적 (backend/core/tracing.py). 서버와 평가 --trace 에서만 켜지고, 보내기 전에 개인정보를 가림
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "inquai"
    langsmith_endpoint: str = ""

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
    # 환불 계좌(예금주·계좌번호) 암호화 열쇠 (backend/services/refund_account.py). 비우면 JWT_SECRET_KEY 에서 만들어 씀
    refund_account_key: str = ""
    refund_account_old_keys: str = ""   # 열쇠를 바꿀 때 예전 열쇠 (쉼표로 여러 개). 서버가 켜지며 새 열쇠로 다시 잠근 뒤 지워도 됨

    # API 문서(/docs, /openapi.json) 공개 여부. 배포에서는 false (공격자에게 API 목록을 보여주지 않게)
    api_docs: bool = True

    # CORS: 쉼표로 여러 주소
    frontend_origins: str = "http://localhost:5173"

    # 분류 모델 폴더와 버전 이름 (docs/model_card.md). 테스트에서는 load_models=false 로 불러오지 않음
    load_models: bool = True
    category_model_dir: Path = PROJECT_ROOT / "models" / "category_classifier"
    sentiment_model_dir: Path = PROJECT_ROOT / "models" / "sentiment_classifier"
    category_model_version: str = "category_aug_s42"
    sentiment_model_version: str = "sentiment_v1"

    # FAQ 검색 (docs/faq_search_eval.md). kure: KURE-v1 + ChromaDB, tfidf: 글자 단위 (모델 없이 가벼움)
    # load_models=false(테스트) 이거나 KURE를 불러오지 못하면 tfidf 로 동작
    faq_search_engine: str = "kure"

    # 고객 답변 알림 메일 (backend/services/notify.py). 꺼져 있으면 기록만 (테스트·CI·Docker 기본)
    mail_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587              # 587 = STARTTLS, 465 = SSL
    smtp_user: str = ""
    smtp_password: str = ""           # Gmail 은 계정 비밀번호가 아니라 '앱 비밀번호'
    mail_from: str = ""               # 비우면 smtp_user
    mail_from_name: str = "InquAI 쇼핑 고객센터"
    mail_redirect_to: str = ""        # 시연용: 모든 답변 알림을 이 주소 하나로 (시연 고객 주소는 가짜라서)
    shop_url: str = "http://localhost:5173"   # 메일의 '문의 조회' 링크 주소

    # 초기 계정 비밀번호 (seed_admin.py)
    seed_admin_password: str = ""
    seed_agent_password: str = ""
    # 시연 고객(customerNN@example.com) 로그인 비밀번호. 비우면 고객 로그인을 쓰지 않음 (쇼핑몰 연동 시연, 4주차)
    seed_customer_password: str = ""
    shop_session_hours: int = 8   # 고객 로그인 유지 시간

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
