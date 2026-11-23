"""답변 기한 (SLA): 긴급도별로 '이 시간 안에 사람이 답해야 한다'는 기준.

    긴급도 높음: 접수 후 4시간 / 그 외: 24시간 — **주말(한국 시간 토·일)은 세지 않음**
    예) 금요일 22:00 긴급 접수 → 금요일 2시간 + 월요일 2시간 → 월요일 02:00
        토요일 접수 → 월요일 00:00부터 셈
    끝난(완료·자동 처리) 문의가 고객 추가 문의로 다시 열리면 그 시각부터 다시 셈 (inquiries.sla_started_at, started())
    평일은 하루 24시간을 모두 셉니다 (시연이라 평일 상담 시간·공휴일은 따지지 않음).
고객에게는 "영업일 기준 1일 이내 답변" 으로 안내하고, 관리자 화면에서는 기한을 넘긴 미처리 문의를 빨갛게 표시합니다.
"""

from datetime import datetime, timedelta, timezone

from backend.database.models import as_utc, utcnow

SLA_HOURS = {"높음": 4}
DEFAULT_HOURS = 24
OPEN_STATUSES = ("접수", "검토 대기", "담당자 처리")
CUSTOMER_NOTICE = "영업일 기준 1일 이내에 답변드립니다. (상담 시간: 평일 10:00~17:00, 점심 12:00~13:00 제외)"
RULE_TEXT = "주말 제외 · 긴급 4시간 · 그 외 24시간"   # 화면 안내용

KST = timezone(timedelta(hours=9))
WEEKEND = timedelta(days=2)


def is_weekend(at: datetime) -> bool:
    return as_utc(at).astimezone(KST).weekday() >= 5


def _week_bounds(at: datetime) -> tuple[datetime, datetime]:
    """at 이 속한 주의 평일 구간: (월요일 00:00, 토요일 00:00) 한국 시간"""
    k = as_utc(at).astimezone(KST)
    monday = (k - timedelta(days=k.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.astimezone(timezone.utc), (monday + timedelta(days=5)).astimezone(timezone.utc)


def add_weekday_time(start: datetime, delta: timedelta) -> datetime:
    """start 에서 주말을 건너뛰며 delta 만큼 뒤 (주말에 시작하면 다음 월요일 00:00부터 셈)"""
    t, left = as_utc(start), delta
    while True:
        monday, saturday = _week_bounds(t)
        if t >= saturday:                      # 주말 → 다음 월요일 00:00
            t = saturday + WEEKEND
            continue
        if t + left <= saturday:
            return t + left
        left -= saturday - t
        t = saturday + WEEKEND


def sub_weekday_time(end: datetime, delta: timedelta) -> datetime:
    """end 에서 주말을 건너뛰며 delta 만큼 앞 (시연 데이터: '평일 기준 n분 전 접수')"""
    t, left = as_utc(end), delta
    while True:
        monday, saturday = _week_bounds(t)
        if t > saturday:                       # 주말 → 그 주 토요일 00:00 (금요일 끝)
            t = saturday
        if t - left >= monday:
            return t - left
        left -= t - monday
        t = monday - WEEKEND                   # 지난주 토요일 00:00


def started(inquiry) -> datetime:
    """기한을 세기 시작한 시각: 다시 열린 문의면 다시 연 시각, 아니면 접수 시각"""
    return inquiry.sla_started_at or inquiry.created_at


def due_at(created_at: datetime, urgency: str | None) -> datetime:
    return add_weekday_time(created_at, timedelta(hours=SLA_HOURS.get(urgency or "", DEFAULT_HOURS)))


def is_overdue(status: str, created_at: datetime, urgency: str | None) -> bool:
    return status in OPEN_STATUSES and utcnow() > due_at(created_at, urgency)
