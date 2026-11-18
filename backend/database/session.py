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
    """테이블이 없으면 만들고, 이미 있는 SQLite 테이블에 새로 추가된 칸이 있으면 붙입니다."""
    from backend.database import models  # noqa: F401  모델을 등록하려고 불러옴

    Base.metadata.create_all(engine)
    if is_sqlite:
        _add_missing_columns()


def _add_missing_columns() -> None:
    """create_all 은 이미 있는 테이블을 바꾸지 않으므로, 기본값이 있거나 비어도 되는 새 칸만 ALTER TABLE 로 추가.

    시연·개발 DB를 다시 만들지 않고 모델에 칸을 더할 수 있게 하는 간단한 방법입니다 (운영에서는 Alembic 같은 마이그레이션 도구).
    """
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing or not (col.nullable or col.server_default is not None):
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(engine.dialect)}'
                if col.server_default is not None:
                    ddl += f" NOT NULL DEFAULT {col.server_default.arg}"
                conn.execute(text(ddl))
