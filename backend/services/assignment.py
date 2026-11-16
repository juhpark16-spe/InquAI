"""상담원 자동 배정: AI가 사람에게 넘기는 문의(검토 대기·담당자 처리)를 담당 유형이 맞는 상담원에게 배정.

규칙
    1. 활성 상담원(role=agent) 중 담당 유형에 이 문의 유형이 있는 사람
    2. 없으면 '전체 담당'(담당 유형을 비워 둔) 상담원
    3. 그중 지금 미처리 문의가 가장 적은 사람 (같으면 먼저 만든 계정)
    4. 아무도 없으면 미배정으로 두고 관리자가 직접 배정
관리자는 언제든 재배정할 수 있습니다 (PATCH /api/inquiries/{id}/assign).
"""

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database.models import AdminAuditLog, AdminUser, Inquiry

OPEN_STATUSES = ("접수", "검토 대기", "담당자 처리")
NEEDS_HUMAN = ("검토 대기", "담당자 처리")


def pick_assignee(db: Session, category: str | None) -> tuple[AdminUser | None, str, dict]:
    """(배정할 상담원, 고른 이유, 후보별 미처리 수)"""
    agents = db.scalars(select(AdminUser).where(AdminUser.role == "agent", AdminUser.is_active.is_(True))
                        .order_by(AdminUser.id)).all()
    specialists = [a for a in agents if category and category in (a.categories or [])]
    generalists = [a for a in agents if not a.categories]
    pool, rule = (specialists, "담당 유형") if specialists else (generalists, "전체 담당")
    if not pool:
        return None, "배정할 상담원 없음", {}

    counts = dict(db.execute(select(Inquiry.assigned_to, func.count())
                             .where(Inquiry.status.in_(OPEN_STATUSES), Inquiry.assigned_to.in_([a.id for a in pool]))
                             .group_by(Inquiry.assigned_to)).all())
    load = {a.id: counts.get(a.id, 0) for a in pool}
    chosen = min(pool, key=lambda a: (load[a.id], a.id))
    return chosen, rule, load


def auto_assign(db: Session, inquiry: Inquiry, category: str | None) -> AdminUser | None:
    """사람이 볼 문의면 배정하고 기록을 남깁니다 (커밋은 부르는 쪽에서)."""
    if inquiry.status not in NEEDS_HUMAN or inquiry.assigned_to is not None:
        return None
    agent, rule, load = pick_assignee(db, category)
    if agent is None:
        return None
    inquiry.assigned_to = agent.id
    # 시스템이 한 일이라 admin_id 는 비움 (관리자 수동 배정은 action=assign)
    db.add(AdminAuditLog(admin_id=None, action="auto_assign", target_type="inquiry", target_id=inquiry.id,
                         detail={"assigned_to": agent.id, "category": category, "rule": rule,
                                 "open_counts": {str(k): v for k, v in load.items()}}))
    return agent
