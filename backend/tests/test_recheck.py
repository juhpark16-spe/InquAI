"""확인 후 다시 안내: 발송하면서 표시 → 목록·상세·알림·대시보드에 보임 → 다음 답변을 보내면 풀림."""

from datetime import timedelta

import pytest

from backend.core.security import hash_password
from backend.database.models import AdminAuditLog, Inquiry, utcnow
from backend.tests.conftest import TEST_PASSWORD

AGENT = 2
LOOKUP_PW = "lookup-pw-1"


def login(client, username="admin"):
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")


@pytest.fixture()
def inquiry_id(db):
    i = Inquiry(inquiry_number="INQ-R-1", customer_name="고객", customer_email="c@example.com", order_number="20261118-0007",
                title="택배가 분실된 것 같아요", content="배송 완료로 나오는데 받지 못했어요", status="담당자 처리", assigned_to=AGENT,
                lookup_password_hash=hash_password(LOOKUP_PW))
    db.add(i)
    db.commit()
    return i.id


def later(hours: float) -> str:
    return (utcnow() + timedelta(hours=hours)).isoformat()


def test_send_with_recheck_then_answer_clears(client, db, inquiry_id):
    login(client, "agent1")
    note = "택배사 분실 조사 결과"
    r = client.post(f"/api/inquiries/{inquiry_id}/responses",
                    json={"text": "택배사에 확인 후 내일 안에 다시 안내드리겠습니다.", "send": True,
                          "recheck": {"note": note, "due_at": later(0.5)}})
    assert r.status_code == 201

    d = client.get(f"/api/inquiries/{inquiry_id}").json()
    assert d["status"] == "완료" and d["overdue"] is False                  # 첫 답변은 보냈으므로 기한 초과 아님
    assert d["recheck"]["note"] == note and d["recheck"]["set_by"] and d["recheck"]["overdue"] is False
    assert any(e["kind"] == "recheck" and e["text"].startswith(f"다시 안내 예정 · {note}") for e in d["history"])

    # 고객 조회: '추가 안내 예정'만 알리고, 확인할 내용(내부 메모)은 보내지 않음
    lookup = client.post("/api/inquiries/lookup", json={"customer_email": "c@example.com", "password": LOOKUP_PW})
    assert lookup.json()["items"][0]["more_answer_coming"] is True and note not in lookup.text

    items = client.get("/api/inquiries?recheck=true").json()["items"]
    assert [i["id"] for i in items] == [inquiry_id] and items[0]["recheck_note"] == note
    bell = client.get("/api/notifications").json()["items"]                  # 기한 1시간 안 → 알림
    assert any(n["kind"] == "recheck" and note in n["text"] for n in bell)

    login(client)
    p = client.get("/api/stats/priorities").json()
    assert p["recheck_total"] == 1 and p["rechecks"][0]["recheck_note"] == note

    # 확인 결과를 보내면(체크 없이) 표시가 풀림
    login(client, "agent1")
    r = client.post(f"/api/inquiries/{inquiry_id}/responses", json={"text": "택배사 확인 결과 분실로 확인되어 재발송합니다.", "send": True})
    assert r.status_code == 201
    d = client.get(f"/api/inquiries/{inquiry_id}").json()
    assert d["recheck"] is None
    assert any(e["text"] == f"다시 안내 완료 · {note} · 다시 안내 답변 발송" for e in d["history"])
    assert client.get("/api/inquiries?recheck=true").json()["total"] == 0
    lookup = client.post("/api/inquiries/lookup", json={"customer_email": "c@example.com", "password": LOOKUP_PW})
    assert lookup.json()["items"][0]["more_answer_coming"] is False


def test_set_change_and_clear_without_answer(client, db, inquiry_id):
    login(client, "agent1")
    url = f"/api/inquiries/{inquiry_id}/recheck"
    assert client.put(url, json={"note": "재고 입고일", "due_at": later(-1)}).status_code == 422      # 지난 시각
    assert client.put(url, json={"note": "재고 입고일", "due_at": later(24 * 15)}).status_code == 422  # 14일 넘음
    assert client.put(url, json={"note": "  ", "due_at": later(24)}).status_code == 422
    assert client.put(url, json={"note": "재고 입고일", "due_at": later(24)}).status_code == 200
    assert client.put(url, json={"note": "재고 입고일 (공급사 회신)", "due_at": later(48)}).status_code == 200
    assert client.get(f"/api/inquiries/{inquiry_id}").json()["recheck"]["note"] == "재고 입고일 (공급사 회신)"
    bell = client.get("/api/notifications").json()["items"]
    assert not any(n["kind"] == "recheck" for n in bell)                      # 기한이 멀면 아직 알리지 않음

    assert client.delete(url).status_code == 200
    assert client.delete(url).status_code == 409
    assert client.get(f"/api/inquiries/{inquiry_id}").json()["recheck"] is None
    actions = [a.action for a in db.query(AdminAuditLog).order_by(AdminAuditLog.id) if a.action.startswith("recheck")]
    assert actions == ["recheck_set", "recheck_set", "recheck_clear"]


def test_recheck_permission_and_draft_approve(client, db, inquiry_id):
    db.get(Inquiry, inquiry_id).assigned_to = 1                               # 다른 사람 담당
    db.commit()
    login(client, "agent1")
    assert client.put(f"/api/inquiries/{inquiry_id}/recheck", json={"note": "x", "due_at": later(2)}).status_code == 403
    db.get(Inquiry, inquiry_id).assigned_to = AGENT
    db.commit()
                                                                              # 초안 저장 → 승인하면서 표시
    draft = client.post(f"/api/inquiries/{inquiry_id}/responses", json={"text": "확인 후 안내드리겠습니다.", "send": False}).json()
    r = client.post(f"/api/responses/{draft['id']}/approve",
                    json={"text": "확인 후 안내드리겠습니다.", "recheck": {"note": "물류센터 확인", "due_at": later(3)}})
    assert r.status_code == 200
    assert client.get(f"/api/inquiries/{inquiry_id}").json()["recheck"]["note"] == "물류센터 확인"
