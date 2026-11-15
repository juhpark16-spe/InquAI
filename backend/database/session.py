"""DB 연결. FastAPI에서는 get_db()를 의존성으로 받아 요청마다 세션 하나를 씁니다."""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.core.config import get_settings

settings = get_settings()
url = settings.resolved_database_url
is_sqlite = url.startswith("sqlite")

engine = create_engine(url, connect_args={"check_same_thread": False} if is_sqlite else {})

if is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")  # SQLite는 외래 키 검사가 기본으로 꺼져 있음
        cur.execute("PRAGMA journal_mode=WAL")  # 읽기·쓰기 동시 처리
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """테이블이 없으면 만듭니다 (있으면 그대로 둠)."""
    from backend.database import models  # noqa: F401  모델을 등록하려고 불러옴

    Base.metadata.create_all(engine)
