"""상담용 주문·고객 상세: 결제·승인 내역(중복 결제 의심), 수량·옵션, 배송 추적, 반품·환불 진행,
같은 주문의 다른 문의, 적립금·쿠폰, 티켓 승인 시 결제 내역 기록."""

from datetime import timedelta

import pytest

from backend.database.models import (Coupon, Customer, Inquiry, Order, Payment, PointHistory, ShipmentEvent, Ticket,
                                     utcnow)
from backend.tests.conftest import TEST_PASSWORD

EMAIL = "lee@example.com"


def login(client):
    client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")


@pytest.fixture()
def data(db):
    now = utcnow()
    c = Customer(name="이서연", email=EMAIL, phone="010-1111-2222")
    db.add(c)
    db.flush()
    paid = now - timedelta(hours=3)
    dup = Order(customer_id=c.id, order_number="P-1", product_name="와이드 데님 팬츠 (연청, 28)", amount=98000, quantity=2,
                order_status="배송 중", shipping_status="대전 HUB 도착", tracking_number="123", carrier="CJ대한통운",
                payment_method="신용카드", paid_at=paid, ordered_at=paid)
    ready = Order(customer_id=c.id, order_number="P-2", product_name="니트 가디건 (아이보리, FREE)", amount=45000,
                  order_status="상품 준비 중", payment_method="간편결제", paid_at=paid, ordered_at=paid)
    db.add_all([dup, ready])
    db.flush()
    db.add_all([
        Payment(order_id=dup.id, kind="승인", method="신용카드", amount=98000, approval_no="11", at=paid),
        Payment(order_id=dup.id, kind="승인", method="신용카드", amount=98000, approval_no="22", at=paid + timedelta(seconds=40)),
        Payment(order_id=ready.id, kind="승인", method="간편결제", amount=45000, approval_no="33", at=paid),
        ShipmentEvent(order_id=dup.id, at=paid + timedelta(hours=1), status="택배사 인수", location="이천 물류센터"),
        ShipmentEvent(order_id=dup.id, at=paid + timedelta(hours=2), status="간선 하차", location="대전 HUB"),
        PointHistory(customer_id=c.id, amount=3000, reason="신규 가입 적립", at=now - timedelta(days=100)),
        PointHistory(customer_id=c.id, amount=-2000, reason="주문 결제에 사용", at=now - timedelta(days=10)),
        PointHistory(customer_id=c.id, amount=450, reason="구매 적립 (구매 확정 후)", status="예정", at=now),
        Coupon(customer_id=c.id, name="무료배송 쿠폰", benefit="배송비 무료", expires_at=now + timedelta(days=5)),
        Coupon(customer_id=c.id, name="지난 쿠폰", benefit="1,000원 할인", expires_at=now - timedelta(days=1)),
    ])
    inquiries = [Inquiry(inquiry_number=f"INQ-T-{n}", customer_name="이서연", customer_email=EMAIL, order_number=o,
                         title=t, content="내용", status="담당자 처리") for n, o, t in
                 [(1, "P-1", "결제가 두 번 됐어요"), (2, "P-1", "배송 언제 와요"), (3, "P-2", "취소해 주세요")]]
    db.add_all(inquiries)
    db.flush()
    db.add(Ticket(inquiry_id=inquiries[2].id, order_id=ready.id, ticket_type="취소", reason="취소", status="접수"))
    db.commit()
    return inquiries


def test_order_card_shows_payments_shipping_quantity_and_related(client, data):
    login(client)
    d = client.get(f"/api/inquiries/{data[0].id}").json()
    o = d["order"]
    assert o["duplicate_payment"] is True                                   # 같은 금액 승인이 40초 간격 두 번
    assert [p["kind"] for p in o["payments"]] == ["승인", "승인"]
    assert (o["quantity"], o["unit_price"], o["option"]) == (2, 49000, "연청, 28")
    assert o["carrier"] == "CJ대한통운" and [e["status"] for e in o["shipment_events"]] == ["택배사 인수", "간선 하차"]
    assert [r["title"] for r in o["related_inquiries"]] == ["배송 언제 와요"]   # 같은 주문의 다른 문의

    p = d["customer_profile"]
    assert (p["points_balance"], p["points_pending"]) == (1000, 450)        # 3000 - 2000, 예정은 잔액에서 제외
    assert [(c["name"], c["state"]) for c in p["coupons"]] == [("무료배송 쿠폰", "사용 가능"), ("지난 쿠폰", "만료")]


def test_cancel_approval_records_payment_cancel(client, db, data):
    login(client)
    ticket = db.query(Ticket).one()
    assert client.patch(f"/api/tickets/{ticket.id}", json={"status": "승인"}).status_code == 200
    o = client.get(f"/api/inquiries/{data[2].id}").json()["order"]
    assert o["order_status"] == "취소"
    assert [(p["kind"], p["amount"]) for p in o["payments"]][-1] == ("승인 취소", 45000)


def test_duplicate_resolved_after_one_cancel(client, db, data):
    order = db.query(Order).filter_by(order_number="P-1").one()
    db.add(Payment(order_id=order.id, kind="승인 취소", method="신용카드", amount=98000, at=utcnow(), memo="중복 승인 1건 취소"))
    db.commit()
    login(client)
    assert client.get(f"/api/inquiries/{data[0].id}").json()["order"]["duplicate_payment"] is False
