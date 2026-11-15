"""Auth API 테스트 (기획서 6장 보안 수칙, docs/api_spec.md 2장)."""

from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.dependencies import AdminOnly
from backend.database.models import AdminAuditLog, AdminUser, RefreshToken
from backend.main import app
from backend.tests.conftest import TEST_PASSWORD


@app.get("/api/_test/admin-only")  # 관리자 전용 의존성을 시험하기 위한 테스트용 주소
def _admin_only(user: AdminOnly):
    return {"ok": True}


def login(client, username="admin", password=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def replace_cookie(client, name, value):
    client.cookies.delete(name)  # 같은 이름 쿠키가 두 개 생기지 않게 지우고 다시 넣음
    client.cookies.set(name, value, path="/api")


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_login_sets_cookies_and_me(client):
    r = login(client)
    assert r.status_code == 200
    assert r.json()["user"] == {"id": 1, "username": "admin", "display_name": "관리자", "role": "admin"}

    set_cookie = r.headers.get_list("set-cookie")
    by_name = {c.split("=", 1)[0]: c.lower() for c in set_cookie}
    assert set(by_name) == {"access_token", "refresh_token", "csrf_token"}
    assert "httponly" in by_name["access_token"] and "httponly" in by_name["refresh_token"]
    assert "httponly" not in by_name["csrf_token"]  # React가 읽어서 헤더에 넣어야 함
    assert all("samesite=lax" in c and "path=/api" in c for c in by_name.values())

    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "admin"


def test_wrong_password_and_unknown_user_same_message(client):
    a = login(client, password="wrong-password")
    b = login(client, username="nobody")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "아이디 또는 비밀번호가 올바르지 않습니다.", "code": "LOGIN_FAILED"}


def test_me_requires_login(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "AUTH_REQUIRED"


def test_lock_after_five_failures_and_auto_unlock(client, db):
    codes = [login(client, password="wrong").status_code for _ in range(5)]
    assert codes == [401, 401, 401, 401, 423]

    locked = login(client)  # 맞는 비밀번호여도 잠김
    assert locked.status_code == 423
    assert locked.json()["code"] == "ACCOUNT_LOCKED" and locked.json()["locked_until"].endswith("Z")

    user = db.scalar(select(AdminUser).where(AdminUser.username == "admin"))
    user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)  # 15분이 지난 것처럼
    db.commit()
    assert login(client).status_code == 200
    db.refresh(user)
    assert user.failed_login_count == 0 and user.locked_until is None


def test_success_resets_failed_count(client, db):
    login(client, password="wrong")
    login(client, password="wrong")
    assert login(client).status_code == 200
    user = db.scalar(select(AdminUser).where(AdminUser.username == "admin"))
    db.refresh(user)
    assert user.failed_login_count == 0


def test_refresh_requires_csrf(client):
    login(client)
    r = client.post("/api/auth/refresh")
    assert r.status_code == 403 and r.json()["code"] == "CSRF_FAILED"
    r = client.post("/api/auth/refresh", headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403


def test_refresh_rotates_and_detects_reuse(client, db):
    login(client)
    old_refresh = client.cookies.get("refresh_token")

    r = client.post("/api/auth/refresh", headers=csrf(client))
    assert r.status_code == 200
    new_refresh = client.cookies.get("refresh_token")
    assert new_refresh != old_refresh

    # 이미 쓴 토큰을 다시 쓰면 401, 그리고 새로 받은 토큰까지 모두 무효화
    replace_cookie(client, "refresh_token", old_refresh)
    stolen = client.post("/api/auth/refresh", headers=csrf(client))
    assert stolen.status_code == 401
    assert db.scalar(select(RefreshToken).where(RefreshToken.revoked_at.is_(None))) is None
    replace_cookie(client, "refresh_token", new_refresh)
    assert client.post("/api/auth/refresh", headers=csrf(client)).status_code == 401


def test_logout_revokes_and_clears(client, db):
    login(client)
    headers = csrf(client)
    refresh_token = client.cookies.get("refresh_token")

    assert client.post("/api/auth/logout").status_code == 403  # CSRF 없이
    r = client.post("/api/auth/logout", headers=headers)
    assert r.status_code == 204
    assert client.get("/api/auth/me").status_code == 401
    record = db.scalar(select(RefreshToken))
    db.refresh(record)
    assert record.revoked_at is not None
    replace_cookie(client, "refresh_token", refresh_token)  # 로그아웃 전 토큰을 다시 넣어 봄
    replace_cookie(client, "csrf_token", headers["X-CSRF-Token"])
    again = client.post("/api/auth/refresh", headers=headers)
    assert again.status_code == 401


def test_expired_access_token(client):
    s = get_settings()
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = jwt.encode({"sub": "1", "role": "admin", "type": "access", "exp": past}, s.jwt_secret_key,
                       algorithm=s.jwt_algorithm)
    replace_cookie(client, "access_token", token)
    r = client.get("/api/auth/me")
    assert r.status_code == 401 and r.json()["code"] == "TOKEN_EXPIRED"


def test_refresh_token_cannot_be_used_as_access(client):
    login(client)
    replace_cookie(client, "access_token", client.cookies.get("refresh_token"))
    assert client.get("/api/auth/me").status_code == 401


def test_admin_only(client):
    login(client, username="agent1")
    r = client.get("/api/_test/admin-only")
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"
    client.cookies.clear()
    login(client)
    assert client.get("/api/_test/admin-only").status_code == 200


def test_audit_logs(client, db):
    login(client, password="wrong")
    login(client, username="nobody")
    login(client)
    client.post("/api/auth/logout", headers=csrf(client))
    logs = db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.id)).all()
    assert [(l.action, l.admin_id, l.detail.get("reason")) for l in logs] == [
        ("login_failed", 1, "wrong_password"), ("login_failed", None, "unknown_user"),
        ("login", 1, None), ("logout", 1, None)]
    assert logs[1].detail["username"] == "nobody"
