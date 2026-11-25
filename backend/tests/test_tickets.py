"""티켓 승인·반려 API 테스트: 취소 승인 → 주문 취소, 출고된 주문은 거절, 반려 사유, 두 번 처리 금지, 권한, 처리 이력."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.database.models import AdminAuditLog, Customer, Inquiry, Order, Ticket, utcnow
from backend.services.sla import is_weekend
from backend.tests.conftest import TEST_PASSWORD


@pytest.fixture()
def tickets(db):
    c = Customer(name="고객", email="t@example.com", phone="010")
    db.add(c)
    db.flush()
    orders = {s: Order(customer_id=c.id, order_number=f"T-{n}", product_name="맨투맨", amount=1, order_status=s,
                       shipping_status=s, ordered_at=utcnow() - timedelta(days=3),
                       delivered_at=utcnow() - timedelta(days=1) if s == "배송 완료" else None)
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
    assert any(e["kind"] == "ticket" and "취소 요청 #" in e["text"] and "승인 · 주문 상품 준비 중 → 취소" in e["text"] for e in history)
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
    # 반품 환불은 [반품 회수 접수] 뒤에만 (배송 완료·기한 확인 + 사유)
    r = client.patch(f"/api/tickets/{tickets['refund']}", json={"status": "승인"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "RETURN_NOT_REQUESTED"
    order = db.scalar(select(Order).where(Order.order_number == "T-2"))
    order.return_requested_at = utcnow()
    db.commit()
    assert client.patch(f"/api/tickets/{tickets['refund']}", json={"status": "승인"}, headers=h).status_code == 200
    db.expire_all()
    refund = next(p for p in db.scalar(select(Order).where(Order.order_number == "T-2")).payments if p.kind == "환불")
    assert refund.status == "예정" and is_weekend(refund.at) is False      # 3영업일 뒤 (주말 아님)
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


def test_approve_needs_same_owner(client, db, tickets):
    """주문번호가 바뀌어 남의 주문이 연결돼도 승인은 막힘 ([바로 처리]와 같은 본인 확인)"""
    stranger = Customer(name="남", email="x@example.com", phone="010")
    db.add(stranger)
    db.flush()
    o = Order(customer_id=stranger.id, order_number="X-1", product_name="니트", amount=1, order_status="상품 준비 중",
              ordered_at=utcnow())
    db.add(o)
    db.flush()
    t = db.get(Ticket, tickets["cancel"])
    t.order_id = o.id
    db.commit()
    h = login(client)
    r = client.patch(f"/api/tickets/{t.id}", json={"status": "승인"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "NOT_OWNER"
    db.expire_all()
    assert db.get(Order, o.id).order_status == "상품 준비 중"                   # 그대로
    assert client.patch(f"/api/tickets/{t.id}", json={"status": "반려", "memo": "본인 확인 안 됨"}, headers=h).status_code == 200


def test_exchange_needs_delivery_within_30_days(client, db, tickets):
    h = login(client, "admin")
    order = db.scalar(select(Order).where(Order.order_number == "T-2"))
    order.delivered_at = utcnow() - timedelta(days=31)
    db.commit()
    r = client.patch(f"/api/tickets/{tickets['others']}", json={"status": "승인"}, headers=h)
    assert r.status_code == 409 and "30일" in r.json()["detail"]


def test_list_excludes_escalations(client, tickets):
    """'상담원 확인 요청'(이관)은 승인·반려 대상이 아니라 목록·건수에서 빠짐 (대시보드 숫자와 같게)"""
    h = login(client, "admin")
    r = client.get("/api/tickets", params={"status": "all"}, headers=h).json()
    assert "이관" not in {t["ticket_type"] for t in r["items"]} and r["counts"]["접수"] == 4


def test_refund_or_exchange_without_order_is_blocked(client, db, tickets):
    t = db.get(Ticket, tickets["refund"])
    t.order_id = None                          # 주문번호를 없는 번호로 바꿔 연결이 끊긴 경우
    db.commit()
    h = login(client)
    r = client.patch(f"/api/tickets/{t.id}", json={"status": "승인"}, headers=h)
    assert r.status_code == 409 and "연결된 주문" in r.json()["detail"]


def test_full_cancel_returns_partial_cancel_fee(client, db, tickets):
    """부분 취소로 뺀 배송비 3,000원은 나머지를 모두 취소하면 함께 돌려줌 (출고 안 됐으니)"""
    from backend.database.models import Payment
    order = db.get(Order, tickets["order"])
    order.amount = 25000
    db.add(Payment(order_id=order.id, kind="승인 취소", amount=22000, at=utcnow(),
                   memo="부분 취소 1개 · 3만원 미만이 되어 배송비 3,000원 차감"))
    db.commit()
    h = login(client)
    assert client.patch(f"/api/tickets/{tickets['cancel']}", json={"status": "승인"}, headers=h).status_code == 200
    db.expire_all()
    last = [p for p in db.get(Order, order.id).payments if p.kind == "승인 취소"][-1]
    assert last.amount == 28000 and "배송비 3,000원 함께 환불" in last.memo
