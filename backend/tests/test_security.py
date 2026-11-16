"""보안 점검에서 찾은 4가지 수정 확인.

1. 비밀번호를 바꾸거나 초기화하면 다른 기기의 access_token 도 즉시 무효
2. 로그인은 같은 IP에서 1분에 10회까지 (비밀번호 스프레이 방지)
3. 모든 응답에 기본 보안 헤더
4. API 문서는 설정(API_DOCS)으로 끌 수 있음
"""

import importlib
import os

from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.main import app
from backend.tests.conftest import TEST_PASSWORD


def login(client, username="agent1", password=TEST_PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_password_change_logs_out_other_devices_now(client):
    with TestClient(app) as other:
        assert login(other).status_code == 200 and other.get("/api/auth/me").status_code == 200
        login(client)
        r = client.post("/api/auth/change-password", headers=csrf(client),
                        json={"current_password": TEST_PASSWORD, "new_password": "brand-new-pass"})
        assert r.status_code == 200
        me = other.get("/api/auth/me")  # 다른 기기: 30분짜리 토큰이 남아 있어도 바로 거부
        assert me.status_code == 401 and "다시 로그인" in me.json()["detail"]
        assert client.get("/api/auth/me").status_code == 200  # 바꾼 화면은 새 토큰으로 유지


def test_admin_reset_logs_out_user_now(client):
    with TestClient(app) as agent:
        login(agent)
        login(client, "admin")
        r = client.post("/api/admin/users/2/reset-password", headers=csrf(client), json={"password": "reset-pass-99"})
        assert r.status_code == 200
        assert agent.get("/api/auth/me").status_code == 401


def test_login_rate_limit_per_ip(client):
    codes = [login(client, f"nouser{i}", "x").status_code for i in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429
    assert login(client).status_code == 429  # 맞는 계정이어도 1분 동안은 막힘


def test_security_headers(client):
    for r in (client.get("/api/health"), client.get("/api/없는주소")):
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_docs_can_be_turned_off(client):
    assert client.get("/docs").status_code == 200  # 개발 기본값: 공개
    os.environ["API_DOCS"] = "false"
    get_settings.cache_clear()
    try:
        import backend.main as main_module
        closed = importlib.reload(main_module).app
        with TestClient(closed) as c:
            assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404
    finally:
        os.environ.pop("API_DOCS")
        get_settings.cache_clear()
        importlib.reload(main_module)
