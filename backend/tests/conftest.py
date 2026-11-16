"""테스트 공통 설정: 개발 DB(data/inquai.db)를 건드리지 않도록 임시 SQLite 파일을 씁니다.

실행 (프로젝트 루트에서)
    python -m pytest backend/tests -q
"""

import os
import tempfile
from pathlib import Path

# backend 를 불러오기 전에 환경 변수를 정해야 설정·DB 연결에 반영됩니다 (.env 보다 우선)
_tmp = Path(tempfile.mkdtemp(prefix="inquai_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-only-for-pytest-0123456789"
os.environ["COOKIE_SECURE"] = "false"
os.environ["LOAD_MODELS"] = "false"   # 분류 모델·LLM은 테스트마다 가짜로 끼움 (test_inquiries.py)
os.environ["OPENAI_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.core import rate_limit  # noqa: E402
from backend.core.security import hash_password  # noqa: E402
from backend.database.models import AdminUser  # noqa: E402
from backend.database.session import Base, SessionLocal, engine  # noqa: E402
from backend.main import app  # noqa: E402

TEST_PASSWORD = "test-password-1234"


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        session.add_all([
            AdminUser(username="admin", role="admin", display_name="관리자", password_hash=hash_password(TEST_PASSWORD)),
            AdminUser(username="agent1", role="agent", display_name="상담원1", password_hash=hash_password(TEST_PASSWORD)),
        ])
        session.commit()
        yield session


@pytest.fixture()
def client(db):
    rate_limit.reset()
    from backend.api.inquiries import lookup_failures
    lookup_failures.reset()
    with TestClient(app) as c:
        yield c
