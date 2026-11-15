"""권한 검사 의존성 (docs/api_spec.md 1장 "권한 표기").

API 함수에서 이렇게 씁니다.
    def my_api(user: LoginUser): ...     # 관리자·상담원 (로그인)
    def my_api(user: AdminOnly): ...     # 관리자만

로그인이 필요한 POST·PUT·PATCH·DELETE 요청은 CSRF 검사도 함께 합니다.
"""

from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backend.core.errors import AppError
from backend.core.security import ACCESS_COOKIE, CSRF_COOKIE, CSRF_HEADER, csrf_matches, decode_token
from backend.database.models import AdminUser
from backend.database.session import get_db

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DB = Annotated[Session, Depends(get_db)]


def verify_csrf(request: Request) -> None:
    if not csrf_matches(request.cookies.get(CSRF_COOKIE), request.headers.get(CSRF_HEADER)):
        raise AppError(403, "요청을 확인할 수 없습니다. 새로고침 후 다시 시도해 주세요.", "CSRF_FAILED")


def get_current_user(request: Request, db: DB) -> AdminUser:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise AppError(401, "로그인이 필요합니다.", "AUTH_REQUIRED")
    try:
        payload = decode_token(token, "access")
    except jwt.ExpiredSignatureError:
        raise AppError(401, "로그인 시간이 만료되었습니다.", "TOKEN_EXPIRED") from None
    except jwt.InvalidTokenError:
        raise AppError(401, "로그인이 필요합니다.", "AUTH_REQUIRED") from None

    user = db.get(AdminUser, int(payload["sub"]))
    if user is None or not user.is_active:
        raise AppError(401, "로그인이 필요합니다.", "AUTH_REQUIRED")
    if request.method not in SAFE_METHODS:
        verify_csrf(request)
    return user


def require_admin(user: Annotated[AdminUser, Depends(get_current_user)]) -> AdminUser:
    if user.role != "admin":
        raise AppError(403, "관리자만 사용할 수 있습니다.", "FORBIDDEN")
    return user


LoginUser = Annotated[AdminUser, Depends(get_current_user)]
AdminOnly = Annotated[AdminUser, Depends(require_admin)]
