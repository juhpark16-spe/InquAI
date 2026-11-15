"""관리자·상담원 작업 기록 (admin_audit_logs)."""

from fastapi import Request
from sqlalchemy.orm import Session

from backend.database.models import AdminAuditLog, AdminUser


def add_audit(db: Session, request: Request, action: str, admin: AdminUser | None,
              target_type: str | None = None, target_id: int | None = None, **detail) -> None:
    """커밋은 부르는 쪽에서 합니다 (작업과 기록이 함께 저장되도록)."""
    detail["ip"] = request.client.host if request.client else None
    db.add(AdminAuditLog(admin_id=admin.id if admin else None, action=action,
                         target_type=target_type, target_id=target_id, detail=detail))
