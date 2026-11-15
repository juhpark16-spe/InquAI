"""Auth API: 로그인, 토큰 재발급, 로그아웃, 내 정보 (docs/api_spec.md 2장)."""

from datetime import timedelta

import jwt
from fastapi import APIRouter, Request, Response
from sqlalchemy import select, update

from backend.core.config import get_settings
from backend.core.dependencies import DB, LoginUser, verify_csrf
from backend.core.errors import AppError
from backend.core.security import (REFRESH_COOKIE, clear_auth_cookies, create_access_token, create_refresh_token,
                                   decode_token, set_auth_cookies, verify_password)
from backend.database.models import AdminUser, RefreshToken, as_utc, utcnow
from backend.schemas.auth import LoginRequest, LoginResponse, UserOut
from backend.services.audit import add_audit

router = APIRouter(prefix="/auth", tags=["Auth"])

LOGIN_FAILED_MESSAGE = "아이디 또는 비밀번호가 올바르지 않습니다."


def _audit(db, request: Request, action: str, user: AdminUser | None, **detail) -> None:
    add_audit(db, request, action, user, target_type="admin_user" if user else None,
              target_id=user.id if user else None, **detail)


def _issue_tokens(db, response: Response, user: AdminUser) -> None:
    refresh, jti, expires_at = create_refresh_token(user.id)
    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=expires_at))
    set_auth_cookies(response, create_access_token(user.id, user.role), refresh)


def _locked_error(locked_until) -> AppError:
    return AppError(423, "로그인을 여러 번 실패해 잠시 잠겼습니다. 잠시 후 다시 시도해 주세요.", "ACCOUNT_LOCKED",
                    locked_until=as_utc(locked_until).isoformat().replace("+00:00", "Z"))


@router.post("/login", response_model=LoginResponse, summary="로그인 (공개)")
def login(body: LoginRequest, request: Request, response: Response, db: DB):
    s = get_settings()
    now = utcnow()
    user = db.scalar(select(AdminUser).where(AdminUser.username == body.username))

    if user is not None and user.locked_until is not None:
        if as_utc(user.locked_until) > now:
            _audit(db, request, "login_failed", user, reason="locked")
            db.commit()
            raise _locked_error(user.locked_until)
        user.failed_login_count, user.locked_until = 0, None  # 잠금 시간이 지나 자동 해제

    password_ok = verify_password(body.password, user.password_hash if user else None)
    if not password_ok or not user.is_active:
        if user is None:
            _audit(db, request, "login_failed", None, username=body.username[:50], reason="unknown_user")
        elif not password_ok:
            user.failed_login_count += 1
            locked = user.failed_login_count >= s.login_max_failures
            if locked:
                user.locked_until = now + timedelta(minutes=s.login_lock_minutes)
            _audit(db, request, "login_failed", user, reason="wrong_password",
                   failed_count=user.failed_login_count, locked=locked)
            if locked:
                db.commit()
                raise _locked_error(user.locked_until)
        else:
            _audit(db, request, "login_failed", user, reason="inactive")
        db.commit()
        raise AppError(401, LOGIN_FAILED_MESSAGE, "LOGIN_FAILED")

    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
    _issue_tokens(db, response, user)
    _audit(db, request, "login", user)
    db.commit()
    return {"user": user}


@router.post("/refresh", response_model=LoginResponse, summary="Access Token 재발급 (refresh_token 쿠키)")
def refresh(request: Request, response: Response, db: DB):
    verify_csrf(request)
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise AppError(401, "로그인이 필요합니다.", "AUTH_REQUIRED")
    try:
        payload = decode_token(token, "refresh")
    except jwt.ExpiredSignatureError:
        raise AppError(401, "로그인 시간이 만료되었습니다. 다시 로그인해 주세요.", "TOKEN_EXPIRED") from None
    except jwt.InvalidTokenError:
        raise AppError(401, "로그인이 필요합니다.", "AUTH_REQUIRED") from None

    record = db.scalar(select(RefreshToken).where(RefreshToken.jti == payload.get("jti")))
    if record is None or record.user_id != int(payload["sub"]):
        raise AppError(401, "로그인이 필요합니다.", "AUTH_REQUIRED")
    now = utcnow()
    if record.revoked_at is not None:
        # 이미 쓴(회전된) 토큰이 다시 들어옴 = 토큰이 새어 나갔을 수 있음 → 이 사용자의 모든 토큰 무효화
        db.execute(update(RefreshToken).where(RefreshToken.user_id == record.user_id,
                                              RefreshToken.revoked_at.is_(None)).values(revoked_at=now))
        db.commit()
        raise AppError(401, "다시 로그인해 주세요.", "AUTH_REQUIRED")

    user = db.get(AdminUser, record.user_id)
    if user is None or not user.is_active:
        raise AppError(401, "로그인이 필요합니다.", "AUTH_REQUIRED")
    record.revoked_at = now  # 토큰 회전: 쓴 토큰은 무효화하고 새로 발급
    _issue_tokens(db, response, user)
    db.commit()
    return {"user": user}


@router.post("/logout", status_code=204, summary="로그아웃")
def logout(request: Request, db: DB):
    """access_token 이 만료된 상태에서도 로그아웃할 수 있도록 refresh_token 쿠키로 사용자를 찾습니다."""
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        verify_csrf(request)
        try:
            payload = decode_token(token, "refresh")
        except jwt.InvalidTokenError:  # 만료 포함: 이미 쓸 수 없는 토큰이라 쿠키만 지움
            payload = None
        if payload:
            record = db.scalar(select(RefreshToken).where(RefreshToken.jti == payload.get("jti")))
            if record is not None and record.revoked_at is None:
                record.revoked_at = utcnow()
                _audit(db, request, "logout", db.get(AdminUser, record.user_id))
                db.commit()
    response = Response(status_code=204)
    clear_auth_cookies(response)
    return response


@router.get("/me", response_model=UserOut, summary="내 정보")
def me(user: LoginUser):
    return user
