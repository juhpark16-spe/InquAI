"""답변 API 테스트: 상담원 직접 작성·발송, 초안 수정·승인, 수정 여부 기록, 권한, 고객 조회 반영."""

import pytest
from sqlalchemy import select

from backend.core.security import hash_password
from backend.database.models import Inquiry, Response
from backend.tests.conftest import TEST_PASSWORD

EMAIL = "cust@example.com"
LOOKUP_PW = "lookup-pw"


@pytest.fixture()
def inquiry(db):
    i = Inquiry(inquiry_number="INQ-R-1", customer_name="고객", customer_email=EMAIL, title="배송 문의",
                content="언제 와요?", status="담당자 처리", assigned_to=2,
                lookup_password_hash=hash_password(LOOKUP_PW))
    other = Inquiry(inquiry_number="INQ-R-2", customer_name="남", customer_email="x@example.com", title="t",
                    content="다른 상담원 문의", status="담당자 처리", assigned_to=None)
    db.add_all([i, other])
    db.commit()
    return i.id


def login(client, username="agent1"):
    client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_write_and_send_directly(client, db, inquiry):
    h = login(client)
    r = client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "  내일 도착 예정입니다.  ", "send": True})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "발송" and body["generated_by"] == "agent_user" and body["final_text"] == "내일 도착 예정입니다."
    assert body["approved_by"] == 2 and body["is_edited"] is False
    db.expire_all()
    assert db.get(Inquiry, inquiry).status == "완료"

    history = [e["text"] for e in client.get(f"/api/inquiries/{inquiry}").json()["history"] if e["kind"] != "mail"]   # 고객 메일 줄은 test_mail
    assert history[-2:] == ["답변 작성", "직접 작성한 답변 발송"]  # 작성 → 발송 순서

    # 고객 조회 화면에 답변이 보임
    client.cookies.clear()
    items = client.post("/api/inquiries/lookup", json={"customer_email": EMAIL, "password": LOOKUP_PW}).json()["items"]
    assert items[0]["answer"] == "내일 도착 예정입니다." and items[0]["status"] == "완료"
    assert [(a["by"], a["text"]) for a in items[0]["answers"]] == [("상담원", "내일 도착 예정입니다.")]


def test_lookup_returns_all_answers_in_order(client, db, inquiry):
    h = login(client)
    client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "첫 답변", "send": True})
    client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "작성 중 초안"})
    client.cookies.clear()
    item = client.post("/api/inquiries/lookup", json={"customer_email": EMAIL, "password": LOOKUP_PW}).json()["items"][0]
    assert [a["text"] for a in item["answers"]] == ["첫 답변"]  # 초안은 고객에게 안 보임
    assert "agent" not in str(item) and "상담원1" not in str(item)  # 상담원 이름·아이디 노출 없음


def test_save_draft_edit_then_approve(client, db, inquiry):
    h = login(client)
    rid = client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "초안"}).json()["id"]
    db.expire_all()
    assert db.get(Inquiry, inquiry).status == "담당자 처리"  # 초안 저장만으로는 그대로

    assert client.put(f"/api/responses/{rid}", headers=h, json={"text": "고친 초안"}).json()["final_text"] == "고친 초안"
    r = client.post(f"/api/responses/{rid}/approve", headers=h)
    assert r.json()["status"] == "발송" and r.json()["final_text"] == "고친 초안"

    history = [e["text"] for e in client.get(f"/api/inquiries/{inquiry}").json()["history"] if e["kind"] != "mail"]   # 고객 메일 줄은 test_mail
    assert history[-3:] == ["답변 작성", "답변 초안 수정", "직접 작성한 답변 발송"]


def test_ai_draft_edited_flag(client, db, inquiry):
    db.add_all([Response(inquiry_id=inquiry, draft_text="AI 초안", generated_by="llm", status="초안")])
    db.commit()
    rid = db.scalar(select(Response.id))
    h = login(client)
    r = client.post(f"/api/responses/{rid}/approve", headers=h, json={"text": "AI 초안을 다듬음"})
    assert r.json()["is_edited"] is True and r.json()["final_text"] == "AI 초안을 다듬음"
    history = [e for e in client.get(f"/api/inquiries/{inquiry}").json()["history"] if e["kind"] != "mail"]
    assert history[-1]["text"] == "AI 초안 수정 후 발송"


def test_ai_draft_unedited(client, db, inquiry):
    db.add(Response(inquiry_id=inquiry, draft_text="AI 초안", generated_by="llm", status="초안"))
    db.commit()
    rid = db.scalar(select(Response.id))
    h = login(client)
    assert client.post(f"/api/responses/{rid}/approve", headers=h).json()["is_edited"] is False


def test_one_pending_draft_only(client, inquiry):
    h = login(client)
    first = client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "초안1"}).json()["id"]
    r = client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "초안2"})
    assert r.status_code == 409 and r.json()["code"] == "DRAFT_EXISTS" and r.json()["response_id"] == first


def test_sent_cannot_change(client, inquiry):
    h = login(client)
    rid = client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "보냄", "send": True}).json()["id"]
    assert client.put(f"/api/responses/{rid}", headers=h, json={"text": "고침"}).json()["code"] == "INVALID_STATE"
    assert client.post(f"/api/responses/{rid}/approve", headers=h).status_code == 400
    # 발송 후에도 추가 답변은 새로 작성 가능
    assert client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "추가 안내"}).status_code == 201


def test_permissions(client, db, inquiry):
    other = db.scalar(select(Inquiry.id).where(Inquiry.inquiry_number == "INQ-R-2"))
    h = login(client)  # agent1: INQ-R-1 만 배정
    assert client.post(f"/api/inquiries/{other}/responses", headers=h, json={"text": "x"}).status_code == 403
    db.add(Response(inquiry_id=other, draft_text="d", status="초안"))
    db.commit()
    rid = db.scalar(select(Response.id).where(Response.inquiry_id == other))
    assert client.put(f"/api/responses/{rid}", headers=h, json={"text": "y"}).status_code == 403
    assert client.post(f"/api/responses/{rid}/approve", headers=h).status_code == 403
    client.cookies.clear()
    h = login(client, "admin")
    assert client.post(f"/api/responses/{rid}/approve", headers=h).status_code == 200  # 관리자는 전체


def test_validation_and_csrf(client, inquiry):
    h = login(client)
    assert client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "   "}).status_code == 422
    assert client.post(f"/api/inquiries/{inquiry}/responses", json={"text": "x"}).status_code == 403  # CSRF
    assert client.post("/api/inquiries/999/responses", headers=h, json={"text": "x"}).status_code == 404


def test_send_with_waiting_ticket_keeps_inquiry_open(client, db, inquiry):
    """승인 대기 중인 취소·교환·반품 요청이 있으면 답변을 보내도 '담당자 처리'로 남음 (요청이 잊히지 않게)"""
    from backend.database.models import Ticket
    db.add(Ticket(inquiry_id=inquiry, ticket_type="취소", reason="취소해 주세요"))
    db.commit()
    h = login(client)
    r = client.post(f"/api/inquiries/{inquiry}/responses", headers=h, json={"text": "확인 후 취소해 드릴게요.", "send": True})
    assert r.status_code == 201 and r.json()["status"] == "발송"
    db.expire_all()
    assert db.get(Inquiry, inquiry).status == "담당자 처리"
