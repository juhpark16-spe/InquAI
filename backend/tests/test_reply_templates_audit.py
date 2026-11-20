"""답변 문구 편집 API와 작업 기록(감사 로그) 조회 API 테스트."""

from backend.services.reply_templates import DEFAULTS
from backend.tests.conftest import TEST_PASSWORD


def login(client, username="admin", password=TEST_PASSWORD):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token") or ""
    return r


def test_defaults_are_seeded_and_staff_can_read(client):
    assert client.get("/api/reply-templates").status_code == 401
    login(client, "agent1")
    items = client.get("/api/reply-templates").json()
    assert [t["label"] for t in items] == [label for label, _ in DEFAULTS]     # 서버가 켜질 때 기본 문구
    assert client.post("/api/reply-templates", json={"label": "x", "text": "문장"}).status_code == 403   # 상담원은 편집 불가


def test_admin_edits_templates_and_everything_is_recorded(client):
    login(client)
    t = client.post("/api/reply-templates", json={"label": "배송 지연 사과", "text": "출고가 늦어져 죄송합니다."}).json()
    assert t["sort_order"] == len(DEFAULTS)
    assert client.post("/api/reply-templates", json={"label": " ", "text": "문장"}).status_code == 422

    r = client.patch(f"/api/reply-templates/{t['id']}", json={"text": "출고가 늦어져 정말 죄송합니다.", "is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    labels = [x["label"] for x in client.get("/api/reply-templates").json()]
    assert "배송 지연 사과" not in labels                                          # 숨긴 문구는 답변 칸에 안 보임
    assert "배송 지연 사과" in [x["label"] for x in client.get("/api/reply-templates?all=true").json()]

    ids = [x["id"] for x in client.get("/api/reply-templates?all=true").json()]
    assert client.put("/api/reply-templates/order", json={"ids": ids[::-1]}).status_code == 200
    assert client.put("/api/reply-templates/order", json={"ids": ids[:2]}).status_code == 422   # 일부만 보내면 거부
    assert client.delete(f"/api/reply-templates/{t['id']}").status_code == 204
    assert client.delete(f"/api/reply-templates/{t['id']}").status_code == 404

    logs = client.get("/api/audit-logs?group=설정").json()["items"]
    actions = [x["action"] for x in logs]
    assert {"template_create", "template_update", "template_reorder", "template_delete"} <= set(actions)
    deleted = next(x for x in logs if x["action"] == "template_delete")
    assert deleted["actor"]["name"] == "관리자" and deleted["target"]["label"] == "배송 지연 사과"   # 지운 문구도 이름으로


def test_audit_log_shows_login_failures_and_is_admin_only(client):
    assert login(client, "admin", "wrong-password-1").status_code == 401
    assert login(client, "nobody", "wrong-password-1").status_code == 401
    login(client, "agent1")
    assert client.get("/api/audit-logs").status_code == 403

    client.cookies.clear()
    login(client)
    r = client.get("/api/audit-logs?group=로그인·보안").json()
    assert r["login_failed"] == 2
    summaries = {x["summary"] for x in r["items"] if x["action"] == "login_failed"}
    assert "비밀번호 틀림" in summaries and "없는 아이디 · 시도한 아이디 'nobody'" in summaries
    unknown = client.get("/api/audit-logs?actor=unknown").json()["items"]
    assert [x["actor"]["name"] for x in unknown] == ["알 수 없음"]
    assert all(x["ip"] for x in r["items"])                                           # 접속 IP 기록
    assert client.get("/api/audit-logs?group=없는묶음").status_code == 422
