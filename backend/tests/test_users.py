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


def test_new_account_must_change_password_before_using_anything(admin, client):
    """관리자가 정한 처음 비밀번호로 로그인하면 새 비밀번호를 정하기 전까지 내 정보·비밀번호 변경·로그아웃만 됨."""
    assert admin.post("/api/admin/users", json=NEW, headers=csrf(admin)).json()["must_change_password"] is True
    client.cookies.clear()
    r = login(client, "agent3", "new-pass-1234")
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is True
    assert client.get("/api/auth/me").json()["must_change_password"] is True

    blocked = client.get("/api/inquiries")
    assert blocked.status_code == 403 and blocked.json()["code"] == "PASSWORD_CHANGE_REQUIRED"
    assert client.get("/api/admin/agent-logs").json()["code"] == "PASSWORD_CHANGE_REQUIRED"

    r = client.post("/api/auth/change-password", json={"current_password": "new-pass-1234", "new_password": "my-own-pass-99"},
                    headers=csrf(client))
    assert r.status_code == 200 and r.json()["user"]["must_change_password"] is False
    assert client.get("/api/inquiries").status_code == 200        # 새 쿠키로 바로 사용 가능


def test_reset_password_requires_change_again(admin, client):
    admin.post("/api/admin/users/2/reset-password", json={"password": "reset-pass-1234"}, headers=csrf(admin))
    assert next(u for u in admin.get("/api/admin/users").json() if u["id"] == 2)["must_change_password"] is True
    client.cookies.clear()
    login(client, "agent1", "reset-pass-1234")
    assert client.get("/api/inquiries").json()["code"] == "PASSWORD_CHANGE_REQUIRED"


def test_seeded_and_existing_accounts_are_not_forced(admin):
    assert admin.get("/api/inquiries").status_code == 200
    assert all(u["must_change_password"] is False for u in admin.get("/api/admin/users").json())


def test_deactivate_moves_open_inquiries(admin, db):
    """비활성화하면 맡던 미처리 문의는 다른 상담원에게 자동 배정 (없으면 미배정), 끝난 문의는 그대로"""
    from backend.core.security import hash_password
    from backend.database.models import AdminUser, AnalysisResult, Inquiry
    other = AdminUser(username="agent2", role="agent", display_name="상담원2", password_hash=hash_password(TEST_PASSWORD))
    db.add(other)
    rows = [Inquiry(inquiry_number=f"INQ-U-{n}", customer_name="c", customer_email="c@example.com", title="t", content="c",
                    status=s, assigned_to=2) for n, s in enumerate(["담당자 처리", "검토 대기", "완료"])]
    db.add_all(rows)
    db.flush()
    db.add(AnalysisResult(inquiry_id=rows[0].id, category="배송", confidence=0.9, sentiment="중립", sentiment_confidence=0.9,
                          urgency="높음", route="조회형", decision="담당자 연결", decided_by="규칙", model_version="t", scores={}))
    db.commit()
    staff = {u["username"]: u for u in admin.get("/api/admin/staff").json()}
    assert staff["agent1"]["open_count"] == 2 and staff["agent1"]["urgent_open"] == 1      # 배정·넘기기 목록의 미처리 수

    assert admin.patch("/api/admin/users/2", json={"is_active": False}, headers=csrf(admin)).status_code == 200
    db.expire_all()
    assert [db.get(Inquiry, r.id).assigned_to for r in rows] == [other.id, other.id, 2]   # 미처리만 agent2 에게
    history = [e["text"] for e in admin.get(f"/api/inquiries/{rows[0].id}").json()["history"]]
    moved = [t for t in history if "계정 비활성화" in t]
    assert len(moved) == 1 and "상담원2" in moved[0]                     # 처리 이력에 한 줄만, 이유와 함께
    assert not any(t.startswith("자동 배정") for t in history)           # 자동 배정 기록이 겹치지 않음 (알림도 한 번)
