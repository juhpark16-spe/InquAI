"""계정 관리 API 테스트 (관리자만): 만들기, 이름·역할·활성 변경, 비밀번호 초기화."""

import pytest
from sqlalchemy import select

from backend.database.models import AdminAuditLog, RefreshToken
from backend.tests.conftest import TEST_PASSWORD

NEW = {"username": "agent3", "display_name": "상담원 박서준", "role": "agent", "password": "new-pass-1234"}


def login(client, username, password=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


@pytest.fixture()
def admin(client):
    assert login(client, "admin").status_code == 200
    return client


def test_agent_cannot_manage_users(client):
    login(client, "agent1")
    assert client.get("/api/admin/users").status_code == 403
    assert client.post("/api/admin/users", json=NEW, headers=csrf(client)).status_code == 403


def test_list_users(admin):
    r = admin.get("/api/admin/users")
    assert r.status_code == 200
    assert [(u["username"], u["role"], u["is_active"]) for u in r.json()] == [("admin", "admin", True),
                                                                              ("agent1", "agent", True)]
    assert "password_hash" not in r.json()[0]


def test_create_user_and_login(admin, client, db):
    r = admin.post("/api/admin/users", json=NEW, headers=csrf(admin))
    assert r.status_code == 201 and r.json()["username"] == "agent3" and r.json()["is_active"] is True
    log = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "user_create"))
    assert log.detail["after"]["username"] == "agent3" and "password" not in str(log.detail)

    client.cookies.clear()
    assert login(client, "agent3", "new-pass-1234").json()["user"]["display_name"] == "상담원 박서준"


def test_duplicate_username(admin):
    r = admin.post("/api/admin/users", json={**NEW, "username": "agent1"}, headers=csrf(admin))
    assert r.status_code == 409 and r.json()["code"] == "USERNAME_TAKEN"


@pytest.mark.parametrize("field,value", [
    ("username", "ab"), ("username", "Agent3"), ("username", "상담원"), ("password", "short"),
    ("role", "superuser"), ("display_name", ""),
])
def test_create_validation(admin, field, value):
    assert admin.post("/api/admin/users", json={**NEW, field: value}, headers=csrf(admin)).status_code == 422


def test_update_name_and_role(admin):
    r = admin.patch("/api/admin/users/2", json={"display_name": "팀장 김하늘", "role": "admin"}, headers=csrf(admin))
    assert r.status_code == 200 and (r.json()["display_name"], r.json()["role"]) == ("팀장 김하늘", "admin")


def test_deactivate_blocks_login_immediately(admin, client, db):
    # agent1 로그인 상태를 따로 만들어 둠
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as agent:
        assert login(agent, "agent1").status_code == 200
        assert agent.get("/api/auth/me").status_code == 200

        r = admin.patch("/api/admin/users/2", json={"is_active": False}, headers=csrf(admin))
        assert r.status_code == 200 and r.json()["is_active"] is False

        assert agent.get("/api/auth/me").status_code == 401              # 기존 access_token 바로 막힘
        assert agent.post("/api/auth/refresh", headers=csrf(agent)).status_code == 401  # refresh 도 무효
    assert db.scalar(select(RefreshToken).where(RefreshToken.user_id == 2, RefreshToken.revoked_at.is_(None))) is None
    assert login(client, "agent1").status_code == 401
    # 비활성 계정은 배정 목록에서 빠짐
    client.cookies.clear()
    login(client, "admin")
    assert [u["username"] for u in client.get("/api/admin/staff").json()] == ["admin"]


def test_cannot_deactivate_or_demote_self(admin):
    for body in ({"is_active": False}, {"role": "agent"}):
        r = admin.patch("/api/admin/users/1", json=body, headers=csrf(admin))
        assert r.status_code == 400 and r.json()["code"] == "INVALID_STATE"
    assert admin.patch("/api/admin/users/1", json={"display_name": "총괄"}, headers=csrf(admin)).status_code == 200


def test_reset_password_unlocks(admin, client, db):
    client2_codes = []
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as other:
        for _ in range(5):
            client2_codes.append(login(other, "agent1", "wrong").status_code)
    assert client2_codes[-1] == 423  # 잠김

    r = admin.post("/api/admin/users/2/reset-password", json={"password": "reset-pass-99"}, headers=csrf(admin))
    assert r.status_code == 200 and r.json()["locked_until"] is None
    assert db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "user_password_reset")) is not None

    client.cookies.clear()
    assert login(client, "agent1", TEST_PASSWORD).status_code == 401
    assert login(client, "agent1", "reset-pass-99").status_code == 200


def test_not_found(admin):
    assert admin.patch("/api/admin/users/999", json={"is_active": False}, headers=csrf(admin)).status_code == 404
    assert admin.post("/api/admin/users/999/reset-password", json={"password": "abcdefgh"},
                      headers=csrf(admin)).status_code == 404
