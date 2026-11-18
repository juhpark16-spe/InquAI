"""문의 상세의 업무 정보: 주문 카드(취소·반품 가능 여부), 같은 고객의 다른 문의, 근거 FAQ 제목, 처리 이력."""

from datetime import timedelta

import pytest

from backend.database.models import (AdminAuditLog, AgentLog, Customer, Faq, Inquiry, Order, Response, utcnow)
from backend.tests.conftest import TEST_PASSWORD

EMAIL = "kim@example.com"


@pytest.fixture()
def setup(db):
    c = Customer(name="김민준", email=EMAIL, phone="010-0000-0000")
    db.add(c)
    db.flush()
    now = utcnow()
    db.add_all([
        Order(customer_id=c.id, order_number="A-1", product_name="맨투맨", amount=39000, order_status="배송 완료",
              shipping_status="배송 완료", tracking_number="111", ordered_at=now - timedelta(days=5),
              delivered_at=now - timedelta(days=3)),
        Order(customer_id=c.id, order_number="A-2", product_name="니트", amount=45000, order_status="상품 준비 중",
              ordered_at=now - timedelta(days=1)),
        Faq(code="F17", category="반품·환불", question="반품 배송비는 얼마인가요?", answer="6,000원"),
    ])
    main = Inquiry(inquiry_number="INQ-1", customer_name="김민준", customer_email=EMAIL, order_number="A-1",
                   title="반품 문의", content="반품하고 싶어요", status="담당자 처리", assigned_to=2,
                   created_at=now - timedelta(minutes=10))
    old = Inquiry(inquiry_number="INQ-0", customer_name="김민준", customer_email=EMAIL, title="이전 문의",
                  content="예전 문의", status="완료", created_at=now - timedelta(days=2))
    other = Inquiry(inquiry_number="INQ-9", customer_name="남", customer_email="other@example.com",
                    order_number="A-2", title="남의 주문", content="취소해 주세요", status="담당자 처리")
    db.add_all([main, old, other])
    db.flush()
    db.add(AgentLog(inquiry_id=main.id, category="반품·환불", confidence=0.9, decision="담당자 연결", decided_by="규칙",
                    selected_tool="상담원 이관", tool_success=True, retrieved_faqs=[["F17", 0.4]],
                    created_at=now - timedelta(minutes=9)))
    db.add(AdminAuditLog(admin_id=None, action="auto_assign", target_type="inquiry", target_id=main.id,
                         detail={"assigned_to": 2, "rule": "전체 담당"}, created_at=now - timedelta(minutes=8)))
    db.add(AdminAuditLog(admin_id=1, action="status_change", target_type="inquiry", target_id=main.id,
                         detail={"before": "검토 대기", "after": "담당자 처리"}, created_at=now - timedelta(minutes=5)))
    db.add(Response(inquiry_id=old.id, draft_text="답", status="발송", used_faq_ids=["F17"]))
    db.commit()
    return {"main": main.id, "old": old.id, "other": other.id}


def login(client, username="admin"):
    client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})


def test_order_card(client, setup):
    login(client)
    o = client.get(f"/api/inquiries/{setup['main']}").json()["order"]
    assert o["found"] and o["email_match"] and o["product_name"] == "맨투맨"
    assert o["cancellable"] is False and o["returnable"] is True  # 배송 완료 3일 → 7일 반품 기한 안
    assert o["return_until"].endswith("Z")


def test_order_email_mismatch_and_cancellable(client, setup):
    login(client)
    o = client.get(f"/api/inquiries/{setup['other']}").json()["order"]
    assert o["email_match"] is False and o["cancellable"] is True and o["returnable"] is False


def test_order_not_found(client, db, setup):
    i = db.get(Inquiry, setup["old"])
    i.order_number = "NOPE"
    db.commit()
    login(client)
    assert client.get(f"/api/inquiries/{setup['old']}").json()["order"] == {**{k: None for k in (
        "email_match", "orderer", "product_name", "amount", "order_status", "shipping_status", "tracking_number",
        "ordered_at", "delivered_at", "cancellable", "return_until", "returnable", "defect_return_until")},
        "found": False, "order_number": "NOPE"}


def test_customer_history_and_faq_titles(client, setup):
    login(client)
    d = client.get(f"/api/inquiries/{setup['main']}").json()
    assert [h["inquiry_number"] for h in d["customer_history"]] == ["INQ-0"]  # 같은 이메일, 자기 자신 제외
    assert d["faq_titles"] == {"F17": "반품 배송비는 얼마인가요?"}


def test_agent_history_only_assigned(client, setup):
    login(client, "agent1")  # agent1(id 2)은 INQ-1만 배정됨
    assert client.get(f"/api/inquiries/{setup['main']}").json()["customer_history"] == []


def test_history_timeline(client, setup):
    login(client)
    texts = [(e["actor"], e["text"]) for e in client.get(f"/api/inquiries/{setup['main']}").json()["history"]]
    assert texts == [("고객", "문의 접수"), ("AI", "담당자 연결 판단 (규칙) · 상담원 이관"),
                     ("시스템", "자동 배정 → 상담원1 (전체 담당)"), ("관리자", "상태 변경: 검토 대기 → 담당자 처리")]


def test_email_orders(client, setup):
    login(client)
    main = client.get(f"/api/inquiries/{setup['main']}").json()
    assert [o["order_number"] for o in main["email_orders"]] == ["A-2"]          # 적은 주문(A-1)은 위 카드에, 나머지만
    no_number = client.get(f"/api/inquiries/{setup['old']}").json()
    assert no_number["order"] is None
    assert [o["order_number"] for o in no_number["email_orders"]] == ["A-2", "A-1"]  # 주문번호 없어도 최신순으로
    assert no_number["email_orders"][0]["cancellable"] is True
    assert client.get(f"/api/inquiries/{setup['other']}").json()["email_orders"] == []  # 이 이메일로 된 주문 없음

def test_mask_phone():
    from backend.services.inquiry_context import mask_phone
    assert mask_phone("010-1234-5678") == "010-****-5678"
    assert mask_phone("01012345678") == "010-****-5678"
    assert mask_phone("123") == "****" and mask_phone(None) is None


def test_customer_profile(client, db, setup):
    r = db.query(Response).filter_by(inquiry_id=setup["old"]).one()
    r.rating = -1                                                     # 이전 답변에 👎
    db.commit()
    login(client)
    p = client.get(f"/api/inquiries/{setup['main']}").json()["customer_profile"]
    assert p == {"member": False, "phone": "010-****-0000", "orders": 2, "inquiries": 2,
                 "negative_inquiries": 0, "negative_ratings": 1}
    other = client.get(f"/api/inquiries/{setup['other']}").json()["customer_profile"]
    assert other["phone"] is None and other["orders"] == 0 and other["inquiries"] == 1   # 쇼핑몰 고객 정보 없음
