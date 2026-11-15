"""여러 API가 같이 쓰는 형식."""

from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator

from backend.database.models import as_utc

# SQLite에서 읽은 날짜는 시간대가 없어 그대로 내보내면 "Z"가 빠집니다.
# UTC로 맞춰 "2026-11-15T05:30:00Z" 형식(docs/api_spec.md 1장)으로 응답합니다.
UTCDateTime = Annotated[datetime, AfterValidator(as_utc)]
