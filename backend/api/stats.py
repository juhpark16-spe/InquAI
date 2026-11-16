"""대시보드 통계: GET /api/stats/summary (관리자, docs/api_spec.md 9장).

기간은 한국 날짜(KST) 기준 from~to (기본: 최근 7일). 문의가 많지 않은 시연 규모라
기간 안의 문의를 한 번에 읽어 파이썬에서 집계합니다 (SQLite·PostgreSQL 어디서나 같은 결과).
"""

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.core.dependencies import DB, AdminOnly
from backend.core.errors import AppError
from backend.services import sla
from backend.database.models import (DECISIONS, INQUIRY_STATUSES, URGENCIES, AdminUser, Inquiry, as_utc)
from backend.training.labels import CATEGORY_LABELS

router = APIRouter(prefix="/stats", tags=["통계"])

KST = timezone(timedelta(hours=9))
OPEN_STATUSES = ("접수", "검토 대기", "담당자 처리")  # 미처리 (자동 처리·완료는 처리됨)
MAX_DAYS = 92
LOW_CONFIDENCE = 0.8


def _kst_today() -> date:
    return datetime.now(KST).date()


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


@router.get("/summary", summary="대시보드 통계 (관리자)")
def summary(
    _: AdminOnly,
    db: DB,
    date_from: date | None = Query(None, alias="from", description="시작일 (KST, 기본: 6일 전)"),
    date_to: date | None = Query(None, alias="to", description="종료일 (KST, 기본: 오늘)"),
):
    today = _kst_today()
    date_to = date_to or today
    date_from = date_from or date_to - timedelta(days=6)
    days = (date_to - date_from).days + 1
    if days < 1 or days > MAX_DAYS:
        raise AppError(422, f"기간은 1~{MAX_DAYS}일로 정해 주세요.", "INVALID_PARAM")

    start = datetime.combine(date_from, time.min, KST).astimezone(timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, KST).astimezone(timezone.utc)
    rows = db.scalars(select(Inquiry).where(Inquiry.created_at >= start, Inquiry.created_at < end)
                      .options(selectinload(Inquiry.analysis), selectinload(Inquiry.agent_logs),
                               selectinload(Inquiry.responses))).all()

    # ---- 날짜별 (유형별 쌓기, 처리·미처리) ----
    daily = {date_from + timedelta(days=i): {"total": 0, "open": 0, "done": 0, "by_category": Counter()}
             for i in range(days)}
    status_c, urgency_c, category_c, decision_c, decided_by_c = Counter(), Counter(), Counter(), Counter(), Counter()
    latencies, tokens_in, tokens_out, llm_calls, errors, low_conf = [], 0, 0, 0, 0, 0
    edited = approved = 0
    ratings = {"ai": Counter(), "agent": Counter()}  # 고객 평가: AI 자동 답변 / 상담원 답변

    for i in rows:
        d = as_utc(i.created_at).astimezone(KST).date()
        bucket = daily[d]
        bucket["total"] += 1
        bucket["open" if i.status in OPEN_STATUSES else "done"] += 1
        status_c[i.status] += 1
        a = i.analysis
        if a:
            bucket["by_category"][a.category] += 1
            category_c[a.category] += 1
            urgency_c[a.urgency] += 1
            if a.decision:
                decision_c[a.decision] += 1
            if a.decided_by:
                decided_by_c[a.decided_by] += 1
            low_conf += a.confidence < LOW_CONFIDENCE
        for log in i.agent_logs:
            if log.latency_ms is not None and log.decided_by == "LLM":
                latencies.append(log.latency_ms)
            t = log.tokens or {}
            tokens_in += t.get("input", 0)
            tokens_out += t.get("output", 0)
            llm_calls += t.get("calls", 0)
            errors += bool(log.error)
        for r in i.responses:
            if r.status == "발송" and r.rating:
                ratings["ai" if r.approved_by is None else "agent"]["up" if r.rating > 0 else "down"] += 1
        for r in i.responses:  # 상담원이 승인한 AI 초안 (자동 발송은 approved_by 없음, 직접 작성은 제외)
            if r.status == "발송" and r.approved_by is not None and r.generated_by == "llm":
                approved += 1
                edited += r.is_edited

    total = len(rows)
    analyzed = sum(category_c.values())

    # ---- 지금 시점의 미처리 현황 (기간과 관계없이 현재 쌓여 있는 일) ----
    open_rows = db.scalars(select(Inquiry).where(Inquiry.status.in_(OPEN_STATUSES))
                           .options(selectinload(Inquiry.analysis))).all()
    urgent_open = sum(1 for i in open_rows if i.analysis and i.analysis.urgency == "높음")
    staff = db.scalars(select(AdminUser).where(AdminUser.is_active.is_(True)).order_by(AdminUser.id)).all()
    per_staff = {s.id: {"id": s.id, "display_name": s.display_name, "role": s.role, "open": 0, "urgent_open": 0}
                 for s in staff}
    for i in open_rows:
        if i.assigned_to in per_staff:
            per_staff[i.assigned_to]["open"] += 1
            per_staff[i.assigned_to]["urgent_open"] += bool(i.analysis and i.analysis.urgency == "높음")

    return {
        "range": {"from": date_from.isoformat(), "to": date_to.isoformat(), "days": days},
        "kpi": {
            "total": total,
            "today": daily[today]["total"] if today in daily else None,
            "auto_rate": _rate(status_c["자동 처리"], analyzed),          # 성공 지표: 30% 이상
            "approval_without_edit_rate": _rate(approved - edited, approved),  # 성공 지표: 70% 이상 (3주차부터)
        },
        "now": {  # 기간과 관계없이 지금 처리해야 할 일
            "open": len(open_rows),
            "urgent_open": urgent_open,
            "review_waiting": sum(1 for i in open_rows if i.status == "검토 대기"),
            "unassigned_open": sum(1 for i in open_rows if i.assigned_to is None),
            "overdue_open": sum(1 for i in open_rows
                                if sla.is_overdue(i.status, i.created_at, i.analysis.urgency if i.analysis else None)),
        },
        "daily": [{"date": d.isoformat(), "total": v["total"], "open": v["open"], "done": v["done"],
                   "by_category": {c: v["by_category"].get(c, 0) for c in CATEGORY_LABELS}}
                  for d, v in daily.items()],
        "by_status": {s: status_c.get(s, 0) for s in INQUIRY_STATUSES},
        "by_category": {c: category_c.get(c, 0) for c in CATEGORY_LABELS},
        "by_urgency": {u: urgency_c.get(u, 0) for u in URGENCIES},
        "by_decision": {d: decision_c.get(d, 0) for d in DECISIONS},
        "by_decided_by": {"규칙": decided_by_c.get("규칙", 0), "LLM": decided_by_c.get("LLM", 0)},
        # 고객 평가 (도움됨 / 도움 안 됨). satisfaction = 도움됨 비율 (평가가 없으면 null)
        "ratings": {k: {"up": c["up"], "down": c["down"], "satisfaction": _rate(c["up"], c["up"] + c["down"])}
                    for k, c in ratings.items()},
        "ai": {
            "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else None,  # LLM이 판단한 문의만
            "low_confidence": low_conf,      # 확신도 0.8 미만 → 담당자 연결
            "llm_calls": llm_calls,
            "tokens": {"input": tokens_in, "output": tokens_out},
            "errors": errors,                # LLM 오류·시간 초과로 검토 대기로 넘어간 건
        },
        "staff": list(per_staff.values()),
    }
