"""비밀번호 해시(Argon2), JWT 발급·검증, 로그인 쿠키 (기획서 6장, docs/api_spec.md 1·2장)."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Response
from pwdlib import PasswordHash

from backend.core.config import get_settings

password_hash = PasswordHash.recommended()  # Argon2
# 없는 아이디로 로그인할 때도 해시 검사를 한 번 해서, 응답 시간으로 아이디 존재 여부를 알 수 없게 함
_DUMMY_HASH = password_hash.hash("dummy-password-for-timing")

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
COOKIE_PATH = "/api"
CSRF_COOKIE_PATH = "/"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    if hashed is None:
        password_hash.verify(password, _DUMMY_HASH)
        return False
    return password_hash.verify(password, hashed)


# ---- JWT -------------------------------------------------------------------
def _secret() -> str:
    key = get_settings().jwt_secret_key
    if len(key) < 32:
        raise RuntimeError(".env 의 JWT_SECRET_KEY 를 32자 이상 무작위 문자열로 넣어 주세요.")
    return key


def create_access_token(user_id: int, role: str, version: int = 0) -> str:
    """version: 계정의 token_version (비밀번호를 바꾸면 올라가 예전 토큰이 무효가 됨)"""
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "type": "access", "ver": version,
               "iat": now, "exp": now + timedelta(minutes=s.access_token_minutes)}
    return jwt.encode(payload, _secret(), algorithm=s.jwt_algorithm)


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    """(토큰, jti, 만료 시각). jti는 DB refresh_tokens 에 기록합니다."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4().hex
    expires_at = now + timedelta(days=s.refresh_token_days)
    payload = {"sub": str(user_id), "jti": jti, "type": "refresh", "iat": now, "exp": expires_at}
    return jwt.encode(payload, _secret(), algorithm=s.jwt_algorithm), jti, expires_at


def decode_token(token: str, token_type: str) -> dict:
    """서명·만료·종류를 확인합니다. 실패하면 jwt.ExpiredSignatureError 또는 jwt.InvalidTokenError."""
    payload = jwt.decode(token, _secret(), algorithms=[get_settings().jwt_algorithm],
                         options={"require": ["sub", "exp", "type"]})
    if payload["type"] != token_type:
        raise jwt.InvalidTokenError("토큰 종류가 다릅니다.")
    return payload


# ---- 쿠키 ------------------------------------------------------------------
def set_auth_cookies(response: Response, access: str, refresh: str) -> str:
    """세 쿠키를 심고 CSRF 토큰을 돌려줍니다.

    csrf_token 은 refresh_token 과 같은 7일로 둡니다. access(30분)와 같게 두면, access가 만료된 뒤
    /api/auth/refresh 를 부를 때 CSRF 값이 이미 사라져 재발급을 할 수 없기 때문입니다.
    """
    s = get_settings()
    csrf = secrets.token_urlsafe(32)
    common = {"secure": s.cookie_secure, "samesite": "lax", "path": COOKIE_PATH}
    response.set_cookie(ACCESS_COOKIE, access, max_age=s.access_token_minutes * 60, httponly=True, **common)
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=s.refresh_token_days * 86400, httponly=True, **common)
    # csrf_token 은 화면 주소(/admin/...)의 React가 document.cookie 로 읽어야 해서 경로를 / 로 둡니다.
    # (Path=/api 이면 /admin 페이지에서 보이지 않음. 토큰 쿠키 두 개는 /api 로만 보냄)
    response.set_cookie(CSRF_COOKIE, csrf, max_age=s.refresh_token_days * 86400, httponly=False,
                        **{**common, "path": CSRF_COOKIE_PATH})
    return csrf


def clear_auth_cookies(response: Response) -> None:
    s = get_settings()
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path=CSRF_COOKIE_PATH if name == CSRF_COOKIE else COOKIE_PATH,
                               secure=s.cookie_secure, samesite="lax", httponly=name != CSRF_COOKIE)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    return bool(cookie_value and header_value) and secrets.compare_digest(cookie_value, header_value)
