"""답변 기한 (SLA): 긴급도별로 '이 시간 안에 사람이 답해야 한다'는 기준.

    긴급도 높음: 접수 후 4시간 / 그 외: 24시간 (시연이라 영업시간·휴일은 따지지 않고 단순 시간으로 계산)
고객에게는 "영업일 기준 1일 이내 답변" 으로 안내하고, 관리자 화면에서는 기한을 넘긴 미처리 문의를 빨갛게 표시합니다.
"""

from datetime import datetime, timedelta

from backend.database.models import as_utc, utcnow

SLA_HOURS = {"높음": 4}
DEFAULT_HOURS = 24
OPEN_STATUSES = ("접수", "검토 대기", "담당자 처리")
CUSTOMER_NOTICE = "영업일 기준 1일 이내에 답변드립니다. (상담 시간: 평일 10:00~17:00, 점심 12:00~13:00 제외)"


def due_at(created_at: datetime, urgency: str | None) -> datetime:
    return as_utc(created_at) + timedelta(hours=SLA_HOURS.get(urgency or "", DEFAULT_HOURS))


def is_overdue(status: str, created_at: datetime, urgency: str | None) -> bool:
    return status in OPEN_STATUSES and utcnow() > due_at(created_at, urgency)
