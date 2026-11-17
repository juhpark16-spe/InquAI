"""분류 수정 (재학습 데이터): API(PATCH /api/inquiries/{id}/analysis)와 시연 데이터 스크립트가 함께 씀."""

from datetime import datetime

from sqlalchemy.orm import Session

from backend.ai.rules import get_route, get_urgency
from backend.database.models import AdminAuditLog, AdminUser, Inquiry, LabelCorrection, utcnow


def apply_correction(db: Session, inquiry: Inquiry, user: AdminUser, *, category: str | None = None,
                     sentiment: str | None = None, ip: str | None = None, at: datetime | None = None) -> dict:
    """바뀐 항목마다 label_corrections(원문 복사본)에 남기고, 처리 경로·긴급도를 규칙으로 다시 계산.

    돌려주는 값: {"changes": {field: [before, after]}, "rule": {route/urgency: [before, after]}} (바뀐 것이 없으면 changes 가 빔)
    커밋은 부르는 쪽에서 합니다.
    """
    a = inquiry.analysis
    at = at or utcnow()
    wanted = {"category": category, "sentiment": sentiment}
    changes = {f: [getattr(a, f), v] for f, v in wanted.items() if v is not None and v != getattr(a, f)}
    if not changes:
        return {"changes": {}, "rule": {}}
    for field, (before, after) in changes.items():
        db.add(LabelCorrection(inquiry_id=inquiry.id, field=field, before_label=before, after_label=after,
                               text=inquiry.content, corrected_by=user.id, created_at=at))
        setattr(a, field, after)
    before_rule = {"route": a.route, "urgency": a.urgency}
    a.route = get_route(a.category)
    a.urgency = get_urgency(a.category, a.sentiment, inquiry.content)
    rule = {k: [before_rule[k], getattr(a, k)] for k in before_rule if before_rule[k] != getattr(a, k)}
    db.add(AdminAuditLog(admin_id=user.id, action="label_correct", target_type="inquiry", target_id=inquiry.id,
                         created_at=at, detail={"changes": changes, "rule": rule, "ip": ip}))
    return {"changes": changes, "rule": rule}
