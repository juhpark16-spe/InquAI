"""FAQ 관리 API 테스트 (관리자만): 목록·등록·수정·비활성, 작업 기록, 검색 색인 바로 반영, 근거로 쓰인 횟수."""

import pytest
from sqlalchemy import select

from backend.database.models import AdminAuditLog, AgentLog, Faq, Inquiry
from backend.tests.conftest import TEST_PASSWORD

NEW = {"category": "배송", "question": "해외 배송도 되나요?", "answer": "현재는 국내 배송만 합니다. 해외 주소로는 보내지 않습니다."}


def login(client, username):
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


@pytest.fixture()
def faqs(db):
    db.add_all([
        Faq(code="F01", category="결제", question="현금영수증 발급되나요?", answer="결제 완료 후 마이페이지에서 신청할 수 있습니다."),
        Faq(code="F02", category="쿠폰·적립금·회원", question="쿠폰은 어디서 받나요?", answer="이벤트 페이지에서 받을 수 있습니다."),
    ])
    db.commit()


@pytest.fixture()
def admin(client, faqs):
    login(client, "admin")
    return client


def test_agent_cannot_manage_faqs(client, faqs):
    login(client, "agent1")
    assert client.get("/api/faqs").status_code == 403
    assert client.post("/api/faqs", json=NEW, headers=csrf(client)).status_code == 403
    assert client.get("/api/faqs/search-test", params={"q": "영수증"}).status_code == 403


def test_needs_login_and_csrf(client, faqs):
    assert client.get("/api/faqs").status_code == 401
    login(client, "admin")
    assert client.post("/api/faqs", json=NEW).status_code == 403          # CSRF 토큰 없음


def test_create_gets_next_code_and_is_searchable_right_away(admin, db):
    before = admin.get("/api/faqs/search-test", params={"q": "해외로 보내 주나요"}).json()["hits"]
    assert all(h["code"] != "F03" for h in before)

    r = admin.post("/api/faqs", json=NEW, headers=csrf(admin))
    assert r.status_code == 201
    assert r.json()["code"] == "F03" and r.json()["used_count"] == 0

    hits = admin.get("/api/faqs/search-test", params={"q": "해외 배송 되나요"}).json()["hits"]
    assert hits[0]["code"] == "F03"                                       # 서버를 다시 켜지 않아도 검색됨
    assert {f["code"] for f in admin.get("/api/public/faqs").json()} == {"F01", "F02", "F03"}
    log = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "faq_create"))
    assert log.detail["after"]["code"] == "F03"


def test_create_validation(admin):
    assert admin.post("/api/faqs", json={**NEW, "code": "F01"}, headers=csrf(admin)).status_code == 409
    assert admin.post("/api/faqs", json={**NEW, "category": "없는유형"}, headers=csrf(admin)).status_code == 422
    assert admin.post("/api/faqs", json={**NEW, "answer": "짧음"}, headers=csrf(admin)).status_code == 422
    assert admin.post("/api/faqs", json={**NEW, "code": "X9"}, headers=csrf(admin)).status_code == 422


def test_update_records_only_changes(admin, db):
    faq = db.scalar(select(Faq).where(Faq.code == "F01"))
    body = {"category": "결제", "question": faq.question, "answer": "결제 완료 후 마이페이지 > 주문 내역에서 신청합니다.",
            "is_active": True}
    r = admin.put(f"/api/faqs/{faq.id}", json=body, headers=csrf(admin))
    assert r.status_code == 200 and "주문 내역" in r.json()["answer"]
    log = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "faq_update"))
    assert set(log.detail["after"]) == {"answer"} and log.detail["code"] == "F01"

    admin.put(f"/api/faqs/{faq.id}", json=body, headers=csrf(admin))       # 바뀐 것 없음 → 기록 안 남김
    assert len(db.scalars(select(AdminAuditLog).where(AdminAuditLog.action == "faq_update")).all()) == 1


def test_deactivate_hides_from_customers_and_search_then_reactivate(admin, db):
    faq = db.scalar(select(Faq).where(Faq.code == "F01"))
    r = admin.delete(f"/api/faqs/{faq.id}", headers=csrf(admin))
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert db.get(Faq, faq.id) is not None                                 # 실제로 지우지 않음
    assert [f["code"] for f in admin.get("/api/public/faqs").json()] == ["F02"]
    assert all(h["code"] != "F01" for h in admin.get("/api/faqs/search-test", params={"q": "현금영수증"}).json()["hits"])
    assert db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "faq_deactivate"))
    assert [f["code"] for f in admin.get("/api/faqs", params={"include_inactive": "false"}).json()] == ["F02"]

    body = {"category": faq.category, "question": faq.question, "answer": faq.answer, "is_active": True}
    assert admin.put(f"/api/faqs/{faq.id}", json=body, headers=csrf(admin)).json()["is_active"] is True
    assert admin.get("/api/faqs/search-test", params={"q": "현금영수증"}).json()["hits"][0]["code"] == "F01"


def test_list_filters_and_usage_count(admin, db):
    i = Inquiry(inquiry_number="INQ-T-0001", customer_name="고객", customer_email="c@example.com", title="t", content="c")
    db.add(i)
    db.flush()
    for used in (["F01"], ["F01", "F02"], []):
        db.add(AgentLog(inquiry_id=i.id, category="결제", confidence=0.9, decision="자동 답변", decided_by="LLM",
                        used_faq_ids=used))
    db.commit()

    rows = {f["code"]: f for f in admin.get("/api/faqs").json()}
    assert rows["F01"]["used_count"] == 2 and rows["F02"]["used_count"] == 1 and rows["F01"]["last_used_at"]
    assert [f["code"] for f in admin.get("/api/faqs", params={"category": "결제"}).json()] == ["F01"]
    assert [f["code"] for f in admin.get("/api/faqs", params={"q": "이벤트"}).json()] == ["F02"]
