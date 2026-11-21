"""답변 기한: 주말(한국 시간 토·일)은 세지 않음 (backend/services/sla.py)"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.services import sla

KST = timezone(timedelta(hours=9))


def k(*args) -> datetime:
    return datetime(*args, tzinfo=KST)


@pytest.mark.parametrize(("created", "urgency", "due"), [
    (k(2026, 11, 18, 10), None, k(2026, 11, 19, 10)),      # 수요일 → 목요일 같은 시각 (평일은 그대로)
    (k(2026, 11, 18, 10), "높음", k(2026, 11, 18, 14)),    # 긴급 4시간
    (k(2026, 11, 20, 22), "높음", k(2026, 11, 23, 2)),     # 금 22시 긴급 → 금 2시간 + 월 2시간
    (k(2026, 11, 20, 10), None, k(2026, 11, 23, 10)),      # 금 10시 → 월 10시 (주말 48시간은 안 셈)
    (k(2026, 11, 21, 15), None, k(2026, 11, 24, 0)),       # 토요일 접수 → 월 00:00부터 24시간
    (k(2026, 11, 22, 23, 59), "높음", k(2026, 11, 23, 4)),  # 일요일 밤 접수 → 월 04:00
])
def test_due_skips_weekend(created, urgency, due):
    assert sla.due_at(created, urgency) == due


def test_weekday_time_round_trip():
    """'평일 기준 n시간 전'(시연 데이터·테스트)에서 기한을 다시 계산하면 지금 + 남은 시간"""
    for now in (k(2026, 11, 19, 5), k(2026, 11, 21, 9), k(2026, 11, 23, 0, 30)):
        for hours in (1, 4, 23.5, 30, 100):
            start = sla.sub_weekday_time(now, timedelta(hours=hours))
            back = sla.add_weekday_time(start, timedelta(hours=hours))
            # 같은 평일 시각인지 (금요일 24:00 = 월요일 00:00 처럼 주말 경계는 같은 시각으로 봄)
            assert sla.add_weekday_time(back, timedelta(0)) == sla.add_weekday_time(now, timedelta(0))
    assert sla.sub_weekday_time(k(2026, 11, 21, 15), timedelta(minutes=50)) == k(2026, 11, 20, 23, 10)   # 토 → 금 23:10
