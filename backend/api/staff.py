"""계정 관리 API (관리자만, docs/api_spec.md 10장).

공개 회원가입은 없고, 관리자가 이 API(계정 관리 화면)로 상담원 계정을 만들고 관리합니다.
    GET   /api/admin/staff                          배정 선택 상자용: 활성 계정만
    GET   /api/admin/users                          계정 목록 (비활성 포함)
    POST  /api/admin/users                          계정 만들기
    PATCH /api/admin/users/{id}                     이름·역할·활성 여부 변경
    POST  /api/admin/users/{id}/reset-password      비밀번호 초기화 (잠금도 풀림)
"""

from fastapi import APIRouter, Request
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from backend.core.dependencies import DB, AdminOnly, LoginUser
from backend.core.errors import AppError
from backend.core.security import hash_password
from backend.database.models import AdminUser, AnalysisResult, Inquiry, RefreshToken, utcnow
from backend.schemas.auth import StaffOut
from backend.schemas.users import PasswordReset, UserCreate, UserDetail, UserUpdate
from backend.services.assignment import OPEN_STATUSES, auto_assign
from backend.services.audit import add_audit

router = APIRouter(prefix="/admin", tags=["계정 관리"])


def _revoke_tokens(db, user_id: int) -> None:
    """로그인 유지(refresh) 토큰을 모두 무효화: 비활성화·비밀번호 초기화 후 기존 로그인이 이어지지 않게."""
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=utcnow()))


def _get_user(db, user_id: int) -> AdminUser:
    user = db.get(AdminUser, user_id)
    if user is None:
        raise AppError(404, "계정을 찾을 수 없습니다.", "NOT_FOUND")
    return user


@router.get("/staff", response_model=list[StaffOut], summary="배정할 수 있는 계정 목록 (로그인: 상담원은 넘길 상대를 고를 때)")
def list_staff(_: LoginUser, db: DB):
    users = db.scalars(select(AdminUser).where(AdminUser.is_active.is_(True))
                       .order_by(AdminUser.role.desc(), AdminUser.id)).all()  # 상담원(agent) 먼저
    # 지금 맡은 미처리 문의 수 (긴급도 높음 따로): 배정·넘기기 때 일이 몰린 사람을 피하게
    rows = db.execute(select(Inquiry.assigned_to, AnalysisResult.urgency)
                      .outerjoin(AnalysisResult, AnalysisResult.inquiry_id == Inquiry.id)
                      .where(Inquiry.status.in_(OPEN_STATUSES), Inquiry.assigned_to.is_not(None))).all()
    load: dict[int, list[int]] = {}
    for uid, urgency in rows:
        n = load.setdefault(uid, [0, 0])
        n[0] += 1
        n[1] += urgency == "높음"
    return [StaffOut(id=u.id, username=u.username, display_name=u.display_name, role=u.role,
                     must_change_password=u.must_change_password, categories=u.categories,
                     open_count=load.get(u.id, [0, 0])[0], urgent_open=load.get(u.id, [0, 0])[1]) for u in users]


@router.get("/users", response_model=list[UserDetail], summary="계정 목록 (관리자)")
def list_users(_: AdminOnly, db: DB):
    return db.scalars(select(AdminUser).order_by(AdminUser.is_active.desc(), AdminUser.role, AdminUser.id)).all()


@router.post("/users", response_model=UserDetail, status_code=201, summary="계정 만들기 (관리자)")
def create_user(body: UserCreate, request: Request, admin: AdminOnly, db: DB):
    if db.scalar(select(AdminUser).where(AdminUser.username == body.username)):
        raise AppError(409, "이미 사용 중인 아이디입니다.", "USERNAME_TAKEN")
    user = AdminUser(username=body.username, display_name=body.display_name, role=body.role,
                     categories=body.categories, password_hash=hash_password(body.password),
                     must_change_password=True)  # 관리자가 정한 처음 비밀번호는 첫 로그인 때 본인이 바꿈
    db.add(user)
    db.flush()
    add_audit(db, request, "user_create", admin, "admin_user", user.id,
              after={"username": user.username, "role": user.role, "display_name": user.display_name,
                     "categories": user.categories})
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserDetail, summary="이름·역할·활성 여부 변경 (관리자)")
def update_user(user_id: int, body: UserUpdate, request: Request, admin: AdminOnly, db: DB):
    user = _get_user(db, user_id)
    changes = body.model_dump(exclude_none=True)
    # 자기 자신을 비활성화하거나 상담원으로 내리면 관리자가 아무도 없게 될 수 있어 막음
    if user.id == admin.id and (changes.get("is_active") is False or changes.get("role") == "agent"):
        raise AppError(400, "자기 계정은 비활성화하거나 상담원으로 바꿀 수 없습니다.", "INVALID_STATE")

    before = {k: (getattr(user, k) or [] if k == "categories" else getattr(user, k)) for k in changes}
    for k, v in changes.items():
        setattr(user, k, v)
    if changes.get("is_active") is False:
        _revoke_tokens(db, user.id)  # access_token(30분)은 요청마다 is_active 를 확인하므로 바로 막힘
        db.flush()   # 비활성 상태를 먼저 반영해야 아래 자동 배정에서 이 사람이 빠짐
        # 맡던 미처리 문의: 아무도 처리하지 못한 채 남지 않게 다른 상담원에게 자동 배정 (맞는 사람이 없으면 미배정 → 관리자 알림)
        for inquiry in db.scalars(select(Inquiry).options(selectinload(Inquiry.analysis))
                                  .where(Inquiry.assigned_to == user.id, Inquiry.status.in_(OPEN_STATUSES))).all():
            inquiry.assigned_to = None
            if inquiry.status == "접수":
                inquiry.status = "담당자 처리"
            moved = auto_assign(db, inquiry, inquiry.analysis.category if inquiry.analysis else None)
            add_audit(db, request, "assign", admin, "inquiry", inquiry.id,
                      before={"assigned_to": user.id, "status": inquiry.status},
                      after={"assigned_to": moved.id if moved else None, "status": inquiry.status},
                      reason=f"{user.display_name} 계정 비활성화")
    if before != changes:
        add_audit(db, request, "user_update", admin, "admin_user", user.id, before=before, after=changes)
    db.commit()
    return user


@router.post("/users/{user_id}/reset-password", response_model=UserDetail, summary="비밀번호 초기화 (관리자)")
def reset_password(user_id: int, body: PasswordReset, request: Request, admin: AdminOnly, db: DB):
    user = _get_user(db, user_id)
    user.password_hash = hash_password(body.password)
    user.failed_login_count, user.locked_until = 0, None  # 잠긴 계정도 풀림
    user.password_changed_at = utcnow()
    user.must_change_password = True  # 관리자가 정한 비밀번호라, 다음 로그인 때 본인이 바꾸게 함
    user.token_version = (user.token_version or 0) + 1  # 그 계정의 기존 로그인을 즉시 끊음
    _revoke_tokens(db, user.id)
    add_audit(db, request, "user_password_reset", admin, "admin_user", user.id)  # 비밀번호는 기록하지 않음
    db.commit()
    return user
