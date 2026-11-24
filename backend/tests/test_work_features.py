"""상담 업무 보강: 이름·주문번호 검색, 답변 없이 종료 사유(고객에게 '종료됨'), 같은 문의 두 번 등록 방지,
두 상담원이 같은 초안을 고칠 때 덮어쓰기 막기(409 STALE), 목록의 새 추가 문의·👎 표시."""

from sqlalchemy import select

from backend.database.models import CustomerMessage, Inquiry, Response, utcnow
from backend.tests.test_customer_features import admin_login, auto_answer, lookup
from backend.tests.test_inquiries import ai, post  # noqa: F401  (ai 는 fixture)


def by_number(db, number):
    return db.scalar(select(Inquiry).where(Inquiry.inquiry_number == number))


def test_search_by_name_and_order(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.5}
    number = post(client, order_number="20261110-0001").json()["inquiry_number"]
    h = admin_login(client)
    assert client.get("/api/inquiries", params={"q": "김민준"}, headers=h).json()["total"] == 1   # 고객 이름
    assert client.get("/api/inquiries", params={"q": "20261110-0001"}, headers=h).json()["items"][0]["inquiry_number"] == number


def test_close_without_answer_shows_reason_to_customer(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.5}
    number = post(client).json()["inquiry_number"]
    inquiry = by_number(db, number)
    h = admin_login(client)
    r = client.patch(f"/api/inquiries/{inquiry.id}/status", json={"status": "완료", "reason": "중복 문의"}, headers=h)
    assert r.status_code == 200
    d = client.get(f"/api/inquiries/{inquiry.id}").json()
    assert d["close_reason"] == "중복 문의" and any(e["text"].endswith("(사유: 중복 문의)") for e in d["history"])
    assert lookup(client).json()["items"][0]["closed_note"] == "같은 내용의 다른 문의에서 안내드려요."
    # 다시 열면 사유가 지워짐
    h = admin_login(client)
    client.patch(f"/api/inquiries/{inquiry.id}/status", json={"status": "담당자 처리"}, headers=h)
    assert lookup(client).json()["items"][0]["closed_note"] is None


def test_same_request_id_returns_same_inquiry(client, db, ai):
    auto_answer(ai)
    first = post(client, client_request_id="req-123").json()
    second = post(client, client_request_id="req-123").json()             # 시간 초과 뒤 다시 누름
    assert first["inquiry_number"] == second["inquiry_number"] and second["answer"] == first["answer"]
    assert db.query(Inquiry).count() == 1
    assert post(client, client_request_id="req-456").json()["inquiry_number"] != first["inquiry_number"]


def test_stale_draft_is_not_overwritten(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.5}
    inquiry = by_number(db, post(client).json()["inquiry_number"])
    h = admin_login(client)
    draft = client.post(f"/api/inquiries/{inquiry.id}/responses", json={"text": "처음 초안", "send": False}, headers=h).json()
    # 상담원 A가 '처음 초안'을 보고 고치는 사이, 상담원 B가 먼저 고침
    assert client.put(f"/api/responses/{draft['id']}", json={"text": "B가 고친 초안", "base": "처음 초안"}, headers=h).status_code == 200
    r = client.put(f"/api/responses/{draft['id']}", json={"text": "A가 고친 초안", "base": "처음 초안"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "STALE"
    r = client.post(f"/api/responses/{draft['id']}/approve", json={"text": "A가 고친 초안", "base": "처음 초안"}, headers=h)
    assert r.status_code == 409
    # 새 내용을 보고(또는 덮어쓰기로 base 없이) 보내면 됨
    assert client.post(f"/api/responses/{draft['id']}/approve", json={"text": "A가 고친 초안", "base": "B가 고친 초안"},
                       headers=h).status_code == 200
    assert db.get(Response, draft["id"]).final_text == "A가 고친 초안"


def test_list_shows_new_follow_up_and_bad_rating(client, db, ai):
    auto_answer(ai)
    inquiry = by_number(db, post(client).json()["inquiry_number"])
    answer = db.scalar(select(Response).where(Response.inquiry_id == inquiry.id))
    answer.rating = -1
    db.add(CustomerMessage(inquiry_id=inquiry.id, content="아직 궁금해요", created_at=utcnow()))
    db.commit()
    h = admin_login(client)
    item = client.get("/api/inquiries", headers=h).json()["items"][0]
    assert item["new_follow_up"] is True and item["bad_rating"] is True
