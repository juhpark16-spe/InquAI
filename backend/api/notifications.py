"""알림 (오른쪽 위 🔔): GET /api/notifications, POST /api/notifications/seen (로그인).

알림을 따로 저장하지 않고, 이미 있는 기록에서 '나에게 해당하는 새 일'을 골라 만듭니다.

| 종류 | 무엇 | 상담원 | 관리자 |
| --- | --- | --- | --- |
| assigned | 문의가 나에게 배정됨 (자동·수동) | 나에게 배정 | 나에게 배정 + 미배정 긴급 문의 접수 |
| followup | 고객 추가 문의 | 내 담당 문의 | 내 담당 + 미배정 문의 |
| due_soon | 답변 기한 1시간 이내 (미처리) | 내 담당 문의 | 내 담당 + 미배정 문의 |
| bad_rating | 고객 👎 '도움 안 됨' | 내가 보낸 답변 | 모든 답변 (AI 자동 답변 포함) |
| recheck | '확인 후 다시 안내' 기한 1시간 전·지남 | 내 담당 문의 | 내 담당 + 미배정 문의 |
| memo | 다른 사람이 남긴 상담원 공유 메모 | 내 담당 문의 | 내 담당 + 미배정 문의 |

- 최근 7일, 최신순 20건. 내가 한 일(내가 나에게 배정 등)은 알리지 않음
- 읽음: 계정의 notifications_seen_at 이후 알림이 '새 알림' (다른 PC에서 로그인해도 이어짐)
- 화면은 30초마다 다시 불러옴 (실시간 연결 없이 단순하게)
"""

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from backend.core.dependencies import DB, LoginUser
from backend.database.models import (AdminAuditLog, AdminUser, CustomerMessage, Inquiry, InquiryNote, Response, as_utc,
                                     utcnow)
from backend.services import sla

router = APIRouter(prefix="/notifications", tags=["알림"])

WINDOW = timedelta(days=7)
DUE_SOON = timedelta(hours=1)
LIMIT = 20


def _item(kind: str, at, inquiry: Inquiry, text: str) -> dict:
    return {"kind": kind, "at": as_utc(at), "inquiry_id": inquiry.id, "inquiry_number": inquiry.inquiry_number,
            "title": inquiry.title, "text": text}


def build(db, user) -> list[dict]:
    """user 에게 보여 줄 알림 (최신순)"""
    now = utcnow()
    since = now - WINDOW
    admin = user.role == "admin"
    mine = Inquiry.assigned_to == user.id
    scope = or_(mine, Inquiry.assigned_to.is_(None)) if admin else mine
    items: list[dict] = []

    # 1. 배정: 자동 배정(detail.assigned_to) · 수동 배정(detail.after.assigned_to). 내가 한 배정은 빼고
    logs = db.scalars(select(AdminAuditLog).where(AdminAuditLog.action.in_(("auto_assign", "assign")),
                                                  AdminAuditLog.target_type == "inquiry",
                                                  AdminAuditLog.created_at >= since)).all()
    to_me = [a for a in logs if a.admin_id != user.id and (
        (a.detail or {}).get("assigned_to") == user.id
        or ((a.detail or {}).get("after") or {}).get("assigned_to") == user.id)]
    inquiries = {i.id: i for i in db.scalars(select(Inquiry).where(Inquiry.id.in_({a.target_id for a in to_me})))} if to_me else {}
    for a in to_me:
        if a.target_id in inquiries and inquiries[a.target_id].assigned_to == user.id:   # 그 뒤 남에게 넘어간 문의는 빼기
            how = "자동 배정" if a.action == "auto_assign" else "배정"
            items.append(_item("assigned", a.created_at, inquiries[a.target_id], f"나에게 {how}된 문의"))
    if admin:   # 관리자: 아무도 맡지 않은 긴급 문의가 들어옴
        urgent = db.scalars(select(Inquiry).options(selectinload(Inquiry.analysis))
                            .where(Inquiry.assigned_to.is_(None), Inquiry.created_at >= since,
                                   Inquiry.status.in_(sla.OPEN_STATUSES))).all()
        items += [_item("assigned", i.created_at, i, "미배정 긴급 문의 접수")
                  for i in urgent if i.analysis and i.analysis.urgency == "높음"]

    # 2. 고객 추가 문의
    rows = db.execute(select(CustomerMessage, Inquiry).join(Inquiry, CustomerMessage.inquiry_id == Inquiry.id)
                      .where(CustomerMessage.created_at >= since, scope)).all()
    items += [_item("followup", m.created_at, i, f"{i.customer_name} 고객의 추가 문의") for m, i in rows]

    # 3. 답변 기한 1시간 이내 (아직 안 지남). 알림 시각 = 기한 1시간 전
    open_rows = db.scalars(select(Inquiry).options(selectinload(Inquiry.analysis))
                           .where(Inquiry.status.in_(sla.OPEN_STATUSES), scope)).all()
    for i in open_rows:
        due = sla.due_at(sla.started(i), i.analysis.urgency if i.analysis else None)
        if now < due <= now + DUE_SOON:
            items.append(_item("due_soon", due - DUE_SOON, i, f"답변 기한 {max(1, round((due - now).total_seconds() / 60))}분 남음"))

    # 3-1. 답변 기한 지남: 담당자에게, 관리자는 모든 담당자의 문의 (팀 전체 지연을 놓치지 않게). 알림 시각 = 기한
    late_rows = open_rows if not admin else db.scalars(
        select(Inquiry).options(selectinload(Inquiry.analysis), selectinload(Inquiry.assignee))
        .where(Inquiry.status.in_(sla.OPEN_STATUSES))).all()
    for i in late_rows:
        due = sla.due_at(sla.started(i), i.analysis.urgency if i.analysis else None)
        if since <= due <= now:
            hours = (now - due).total_seconds() / 3600
            late = f"{max(1, round(hours * 60))}분" if hours < 1 else f"{round(hours)}시간"
            who = "" if i.assigned_to == user.id else f" · 담당 {i.assignee.display_name if i.assignee else '미배정'}"
            items.append(_item("overdue", due, i, f"답변 기한 {late} 지남{who}"))

    # 4. 고객 👎 평가
    stmt = (select(Response, Inquiry).join(Inquiry, Response.inquiry_id == Inquiry.id)
            .where(Response.rating < 0, Response.rated_at >= since))
    if not admin:
        stmt = stmt.where(Response.approved_by == user.id)
    for r, i in db.execute(stmt).all():
        who = "AI 자동 답변" if r.approved_by is None else "내 답변" if r.approved_by == user.id else "상담원 답변"
        items.append(_item("bad_rating", r.rated_at, i, f"{who}에 고객이 '도움 안 됨'을 남김"))

    # 5. 다시 안내 기한: 1시간 전부터 (지나도 풀 때까지 남음). 알림 시각 = 기한 1시간 전
    for i in db.scalars(select(Inquiry).where(Inquiry.recheck_due_at.is_not(None), scope)).all():
        due = as_utc(i.recheck_due_at)
        if due <= now + DUE_SOON:
            left = round((due - now).total_seconds() / 60)
            when = f"{left}분 남음" if left > 0 else "기한 지남"
            items.append(_item("recheck", due - DUE_SOON, i, f"다시 안내 {when} · {i.recheck_note}"))

    # 6. 다른 사람이 남긴 상담원 공유 메모 (내가 남긴 메모는 알리지 않음)
    rows = db.execute(select(InquiryNote, Inquiry, AdminUser.display_name)
                      .join(Inquiry, InquiryNote.inquiry_id == Inquiry.id)
                      .join(AdminUser, InquiryNote.author_id == AdminUser.id)
                      .where(InquiryNote.created_at >= since, InquiryNote.author_id != user.id, scope)).all()
    items += [_item("memo", n.created_at, i, f"{name}님의 새 상담원 공유 메모: {n.text[:40]}") for n, i, name in rows]

    items.sort(key=lambda x: x["at"], reverse=True)
    return items[:LIMIT]


@router.get("", summary="내 알림 (로그인)")
def list_notifications(user: LoginUser, db: DB):
    items = build(db, user)
    seen = as_utc(user.notifications_seen_at) if user.notifications_seen_at else None
    for x in items:
        x["unread"] = seen is None or x["at"] > seen
    return {"unread": sum(x["unread"] for x in items), "items": items}


@router.post("/seen", summary="알림을 모두 읽음으로 (로그인)")
def mark_seen(user: LoginUser, db: DB):
    user.notifications_seen_at = utcnow()
    db.commit()
    return {"seen_at": user.notifications_seen_at}
