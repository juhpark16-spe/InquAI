"""티켓 승인·반려 API 테스트: 취소 승인 → 주문 취소, 출고된 주문은 거절, 반려 사유, 두 번 처리 금지, 권한, 처리 이력."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.database.models import AdminAuditLog, Customer, Inquiry, Order, Ticket, utcnow
from backend.tests.conftest import TEST_PASSWORD


@pytest.fixture()
def tickets(db):
    c = Customer(name="고객", email="t@example.com", phone="010")
    db.add(c)
    db.flush()
    orders = {s: Order(customer_id=c.id, order_number=f"T-{n}", product_name="맨투맨", amount=1, order_status=s,
                       shipping_status=s, ordered_at=utcnow() - timedelta(days=1))
              for n, s in enumerate(["상품 준비 중", "배송 중", "배송 완료"])}
    db.add_all(orders.values())
    i = Inquiry(inquiry_number="INQ-T-0001", customer_name="고객", customer_email="t@example.com", title="t",
                content="c", status="검토 대기", assigned_to=2)   # agent1
    other = Inquiry(inquiry_number="INQ-T-0002", customer_name="고객", customer_email="t@example.com", title="t",
                    content="c", status="검토 대기", assigned_to=None)
    db.add_all([i, other])
    db.flush()
    made = {
        "cancel": Ticket(inquiry_id=i.id, order_id=orders["상품 준비 중"].id, ticket_type="취소", reason="r"),
        "cancel_shipped": Ticket(inquiry_id=i.id, order_id=orders["배송 중"].id, ticket_type="취소", reason="r"),
        "refund": Ticket(inquiry_id=i.id, order_id=orders["배송 완료"].id, ticket_type="환불", reason="r"),
        "escalate": Ticket(inquiry_id=i.id, ticket_type="이관", reason="r"),
        "others": Ticket(inquiry_id=other.id, order_id=orders["배송 완료"].id, ticket_type="교환", reason="r"),
    }
    db.add_all(made.values())
    db.commit()
    return {k: t.id for k, t in made.items()} | {"inquiry": i.id, "order": orders["상품 준비 중"].id}


def login(client, username="agent1"):
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_approve_cancel_cancels_order(client, db, tickets):
    h = login(client)
    r = client.patch(f"/api/tickets/{tickets['cancel']}", json={"status": "승인"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "승인" and r.json()["handled_by"] == 2
    db.expire_all()
    assert db.get(Order, tickets["order"]).order_status == "취소"
    log = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "ticket_approve"))
    assert log.detail["order"] == {"order_number": "T-0", "before": "상품 준비 중", "after": "취소"}
    history = client.get(f"/api/inquiries/{tickets['inquiry']}").json()["history"]
    assert any(e["kind"] == "ticket" and "취소 승인 · 주문 상품 준비 중 → 취소" in e["text"] for e in history)
    # 두 번 처리할 수 없음
    assert client.patch(f"/api/tickets/{tickets['cancel']}", json={"status": "반려", "memo": "x"},
                        headers=h).json()["code"] == "TICKET_DONE"


def test_shipped_order_cannot_be_cancelled(client, tickets):
    h = login(client)
    r = client.patch(f"/api/tickets/{tickets['cancel_shipped']}", json={"status": "승인"}, headers=h)
    assert r.status_code == 409 and "반품" in r.json()["detail"]
    r = client.patch(f"/api/tickets/{tickets['cancel_shipped']}", json={"status": "반려", "memo": "이미 출고, 반품 안내"},
                     headers=h)
    assert r.status_code == 200 and r.json()["memo"] == "이미 출고, 반품 안내"


def test_reject_needs_memo_and_refund_approve_keeps_order(client, db, tickets):
    h = login(client)
    assert client.patch(f"/api/tickets/{tickets['refund']}", json={"status": "반려", "memo": "  "},
                        headers=h).status_code == 422
    assert client.patch(f"/api/tickets/{tickets['refund']}", json={"status": "승인"}, headers=h).status_code == 200
    db.expire_all()
    assert db.get(Ticket, tickets["refund"]).status == "승인"
    assert db.scalar(select(Order).where(Order.order_number == "T-2")).order_status == "배송 완료"


def test_escalation_ticket_is_not_actionable(client, tickets):
    h = login(client)
    assert client.patch(f"/api/tickets/{tickets['escalate']}", json={"status": "승인"}, headers=h).status_code == 422


def test_permissions(client, tickets):
    assert client.patch(f"/api/tickets/{tickets['cancel']}", json={"status": "승인"}).status_code == 401
    h = login(client)
    assert client.patch(f"/api/tickets/{tickets['others']}", json={"status": "승인"}, headers=h).status_code == 403
    assert client.patch("/api/tickets/9999", json={"status": "승인"}, headers=h).status_code == 404
    client.post("/api/auth/logout", headers=h)
    h = login(client, "admin")
    assert client.patch(f"/api/tickets/{tickets['others']}", json={"status": "승인"}, headers=h).status_code == 200
