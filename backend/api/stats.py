"""대시보드 통계: GET /api/stats/summary (관리자, docs/api_spec.md 9장).

기간은 한국 날짜(KST) 기준 from~to (기본: 최근 7일). 문의가 많지 않은 시연 규모라
기간 안의 문의를 한 번에 읽어 파이썬에서 집계합니다 (SQLite·PostgreSQL 어디서나 같은 결과).
"""

import re
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.core.dependencies import DB, AdminOnly
from backend.core.errors import AppError
from backend.services import sla
from backend.services.inquiry_context import history
from backend.database.models import (DECISIONS, INQUIRY_STATUSES, URGENCIES, AdminUser, Inquiry, LabelCorrection,
                                     Order, as_utc)
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


def _load(db, date_from: date, date_to: date) -> list[Inquiry]:
    """KST 날짜 from~to 사이에 접수된 문의 (분석·AI 기록·답변 함께)"""
    start = datetime.combine(date_from, time.min, KST).astimezone(timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, KST).astimezone(timezone.utc)
    return db.scalars(select(Inquiry).where(Inquiry.created_at >= start, Inquiry.created_at < end)
                      .options(selectinload(Inquiry.analysis), selectinload(Inquiry.agent_logs),
                               selectinload(Inquiry.responses))).all()


def _avg_latency(rows: list[Inquiry]) -> int | None:
    """LLM이 판단한 문의의 평균 처리 시간 (ms)"""
    values = [log.latency_ms for i in rows for log in i.agent_logs
              if log.latency_ms is not None and log.decided_by == "LLM"]
    return round(sum(values) / len(values)) if values else None


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

    rows = _load(db, date_from, date_to)
    # 바로 앞의 같은 길이 기간 (대시보드의 "지난 기간 대비" 증감)
    prev_to = date_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=days - 1)
    prev_rows = _load(db, prev_from, prev_to)

    # ---- 날짜별 (유형별 쌓기, 처리·미처리) ----
    daily = {date_from + timedelta(days=i): {"total": 0, "open": 0, "done": 0, "auto": 0, "by_category": Counter()}
             for i in range(days)}
    status_c, urgency_c, category_c, decision_c, decided_by_c = Counter(), Counter(), Counter(), Counter(), Counter()
    tokens_in, tokens_out, llm_calls, errors, draft_failures, low_conf = 0, 0, 0, 0, 0, 0
    edited = approved = 0
    ratings = {"ai": Counter(), "agent": Counter()}  # 고객 평가: AI 자동 답변 / 상담원 답변

    for i in rows:
        d = as_utc(i.created_at).astimezone(KST).date()
        bucket = daily[d]
        bucket["total"] += 1
        bucket["open" if i.status in OPEN_STATUSES else "done"] += 1
        bucket["auto"] += i.status == "자동 처리"
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
            t = log.tokens or {}
            tokens_in += t.get("input", 0)
            tokens_out += t.get("output", 0)
            llm_calls += t.get("calls", 0)
            if log.error and log.error.startswith("초안 작성 실패"):
                draft_failures += 1      # 판단은 됐고 초안만 못 씀 (상담원이 버튼으로 다시 만들 수 있음)
            else:
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

    # 기간 안에 상담원이 고친 분류 (재학습 데이터, 모델이 자주 틀리는 유형을 보는 데도 씀)
    start = datetime.combine(date_from, time.min, KST).astimezone(timezone.utc)
    end = datetime.combine(date_to + timedelta(days=1), time.min, KST).astimezone(timezone.utc)
    fixes = db.scalars(select(LabelCorrection).where(LabelCorrection.created_at >= start,
                                                     LabelCorrection.created_at < end)).all()
    corrections = {"category": sum(c.field == "category" for c in fixes),
                   "sentiment": sum(c.field == "sentiment" for c in fixes),
                   "by_category": dict(Counter(c.before_label for c in fixes if c.field == "category"))}  # AI가 고른 유형

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
        "previous": {  # 바로 앞 기간 (같은 일수). 증감 비교용
            "from": prev_from.isoformat(), "to": prev_to.isoformat(),
            "total": len(prev_rows),
            "auto_rate": _rate(sum(i.status == "자동 처리" for i in prev_rows), sum(i.analysis is not None for i in prev_rows)),
            "avg_latency_ms": _avg_latency(prev_rows),
        },
        "now": {  # 기간과 관계없이 지금 처리해야 할 일
            "open": len(open_rows),
            "urgent_open": urgent_open,
            "review_waiting": sum(1 for i in open_rows if i.status == "검토 대기"),
            "unassigned_open": sum(1 for i in open_rows if i.assigned_to is None),
            "overdue_open": sum(1 for i in open_rows
                                if sla.is_overdue(i.status, i.created_at, i.analysis.urgency if i.analysis else None)),
        },
        "daily": [{"date": d.isoformat(), "total": v["total"], "open": v["open"], "done": v["done"], "auto": v["auto"],
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
            "avg_latency_ms": _avg_latency(rows),  # LLM이 판단한 문의만
            "low_confidence": low_conf,      # 확신도 0.8 미만 → 담당자 연결
            "llm_calls": llm_calls,
            "tokens": {"input": tokens_in, "output": tokens_out},
            "errors": errors,                # LLM 오류·시간 초과로 검토 대기로 넘어간 건
            "draft_failures": draft_failures,  # 판단 뒤 답변 초안 작성만 실패한 건
            "corrections": corrections,      # 상담원이 고친 분류 (유형·감정)
        },
        "staff": list(per_staff.values()),
    }


@router.get("/activity", summary="최근 처리 활동 (관리자)")
def activity(_: AdminOnly, db: DB, limit: int = Query(8, ge=1, le=30)):
    """최근에 움직임이 있던 문의들의 처리 이력(접수, AI 판단, 배정, 상태 변경, 발송)을 최신순으로"""
    recent = db.scalars(select(Inquiry).order_by(Inquiry.updated_at.desc(), Inquiry.id.desc()).limit(limit * 2)
                        .options(selectinload(Inquiry.agent_logs), selectinload(Inquiry.responses),
                                 selectinload(Inquiry.messages))).all()
    events = [{**e, "inquiry_id": i.id, "inquiry_number": i.inquiry_number, "title": i.title}
              for i in recent for e in history(db, i)]
    events.sort(key=lambda e: as_utc(e["at"]), reverse=True)
    return [{**e, "at": as_utc(e["at"]).isoformat()} for e in events[:limit]]


# ---- 상품별 문의 (4주차, 채널톡 '주문 연동 상담' 벤치마킹) --------------------------------------
# 같은 상품에 문의가 몰리면 상세페이지가 고객에게 충분히 설명하지 못한다는 신호. 가장 많은 유형에 맞춰 개선 힌트를 붙임
PRODUCT_HINTS = {
    "상품": "소재·사이즈·사용법 질문이 많아요 → 상세페이지 설명·실측 정보 보강",
    "교환": "교환이 많아요 → 사이즈표·색상 실물 사진 보강",
    "반품·환불": "반품이 많아요 → 설명과 실물 차이, 품질 점검",
    "배송": "배송 문의가 많아요 → 출고 일정·배송 기간 안내 보강",
    "주문 취소": "취소가 많아요 → 옵션 선택 안내·배송 일정 확인",
    "결제": "결제 문의가 많아요 → 결제 수단·할부 안내 확인",
    "쿠폰·적립금·회원": "쿠폰·적립 문의가 많아요 → 혜택 적용 조건 표시 확인",
    "기타": "기타 문의가 많아요 → 문의 내용을 직접 확인",
}
OPTION = re.compile(r"\s*\([^()]*\)\s*$")   # "와이드 데님 팬츠 (연청, 28)" → "와이드 데님 팬츠" (옵션이 달라도 같은 상품)


def product_base(name: str) -> str:
    return OPTION.sub("", name).strip() or name


@router.get("/products", summary="상품별 문의 (관리자)")
def products(
    _: AdminOnly,
    db: DB,
    date_from: date | None = Query(None, alias="from", description="시작일 (KST, 기본: 29일 전)"),
    date_to: date | None = Query(None, alias="to", description="종료일 (KST, 기본: 오늘)"),
    limit: int = Query(5, ge=1, le=20),
):
    date_to = date_to or _kst_today()
    date_from = date_from or date_to - timedelta(days=29)
    if date_from > date_to or (date_to - date_from).days >= MAX_DAYS:
        raise AppError(422, f"기간은 시작일 이후, 최대 {MAX_DAYS}일입니다.", "INVALID_PARAM")
    rows = _load(db, date_from, date_to)
    numbers = {i.order_number for i in rows if i.order_number}
    orders = {o.order_number: o for o in db.scalars(select(Order).where(Order.order_number.in_(numbers)))} if numbers else {}

    groups: dict[str, list[Inquiry]] = {}
    for i in rows:
        order = orders.get(i.order_number or "")
        if order:   # 실제 주문에 연결된 문의만 (주문번호를 잘못 적은 문의는 빠짐)
            groups.setdefault(product_base(order.product_name), []).append(i)

    items = []
    for product, inqs in groups.items():
        cats = Counter(i.analysis.category for i in inqs if i.analysis)
        ranked = cats.most_common(2)
        # 힌트는 한 유형이 2건 이상이고 다른 유형보다 분명히 많을 때만 (1·1·1처럼 고르게 나뉘면 신호가 아님)
        clear = bool(ranked) and ranked[0][1] >= 2 and (len(ranked) == 1 or ranked[0][1] > ranked[1][1])
        top = ranked[0][0] if clear else None
        last_logs = [max(i.agent_logs, key=lambda log: log.id) for i in inqs if i.agent_logs]
        items.append({
            "product": product,
            "count": len(inqs),
            "by_category": dict(cats.most_common()),
            "top_category": top,
            "negative": sum(1 for i in inqs if i.analysis and i.analysis.sentiment == "부정"),
            "auto": sum(1 for log in last_logs if log.decision == "자동 답변"),
            "hint": PRODUCT_HINTS.get(top) if top else None,
            "examples": [{"inquiry_id": i.id, "inquiry_number": i.inquiry_number, "title": i.title,
                          "category": i.analysis.category if i.analysis else None}
                         for i in sorted(inqs, key=lambda x: x.created_at, reverse=True)[:3]],
        })
    items.sort(key=lambda x: (-x["count"], x["product"]))
    return {"range": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "total": len(rows), "linked": sum(len(v) for v in groups.values()), "products": len(groups),
            "items": items[:limit]}
