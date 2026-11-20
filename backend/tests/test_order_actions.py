"""문의 상세의 바로 처리: 조건이 맞을 때만 처리되고, 결과가 주문·결제·적립금·쿠폰·기록에 남는지."""

from datetime import timedelta

import pytest

from backend.database.models import (AdminAuditLog, Coupon, Customer, Inquiry, Order, Payment, PointHistory, Ticket,
                                     utcnow)
from backend.tests.conftest import TEST_PASSWORD

EMAIL = "park@example.com"
AGENT = 2


def login(client, username="admin"):
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")


@pytest.fixture()
def ids(db):
    now = utcnow()
    c = Customer(name="박지호", email=EMAIL, phone="010-3333-4444")
    other = Customer(name="남", email="other@example.com", phone="010-0000-1111")
    db.add_all([c, other])
    db.flush()
    paid = now - timedelta(hours=2)
    orders = {
        "ready": Order(customer_id=c.id, order_number="R-1", product_name="와이드 데님 팬츠 (연청, 28)", amount=98000, quantity=2,
                       order_status="상품 준비 중", payment_method="신용카드", paid_at=paid, ordered_at=paid,
                       shipping_address="서울 마포구 월드컵로 1"),
        "shipped": Order(customer_id=c.id, order_number="S-1", product_name="니트 가디건 (아이보리, FREE)", amount=45000,
                         order_status="배송 중", payment_method="간편결제", paid_at=paid, ordered_at=paid),
        "delivered": Order(customer_id=c.id, order_number="D-1", product_name="가죽 크로스백 (브라운)", amount=79000,
                           order_status="배송 완료", ordered_at=now - timedelta(days=5), delivered_at=now - timedelta(days=3)),
        "old": Order(customer_id=c.id, order_number="D-2", product_name="가죽 크로스백 (블랙)", amount=79000,
                     order_status="배송 완료", ordered_at=now - timedelta(days=15), delivered_at=now - timedelta(days=12)),
        "notmine": Order(customer_id=other.id, order_number="X-1", product_name="니트 가디건 (베이지, FREE)", amount=45000,
                         order_status="결제 완료", ordered_at=paid),
    }
    db.add_all(orders.values())
    db.flush()
    db.add_all([
        Payment(order_id=orders["ready"].id, kind="승인", method="신용카드", amount=98000, approval_no="A1", at=paid),
        Payment(order_id=orders["ready"].id, kind="승인", method="신용카드", amount=98000, approval_no="A2", at=paid + timedelta(seconds=40)),
    ])
    out = {}
    for key, o in orders.items():
        i = Inquiry(inquiry_number=f"INQ-A-{key}", customer_name="박지호", customer_email=EMAIL, order_number=o.order_number,
                    title=key, content="내용", status="담당자 처리", assigned_to=AGENT)
        db.add(i)
        db.flush()
        out[key] = i.id
    db.add(Ticket(inquiry_id=out["ready"], order_id=orders["ready"].id, ticket_type="취소", reason="1개만 취소", status="접수"))
    db.commit()
    return out


def act(client, inquiry_id, **body):
    return client.post(f"/api/inquiries/{inquiry_id}/actions", json=body)


def order(db, number):
    db.expire_all()
    return db.query(Order).filter_by(order_number=number).one()


def test_address_and_option_only_before_shipping(client, db, ids):
    login(client, "agent1")
    assert act(client, ids["ready"], action="address", address="경기 성남시 분당구 판교역로 166").status_code == 200
    assert order(db, "R-1").shipping_address == "경기 성남시 분당구 판교역로 166"
    assert act(client, ids["shipped"], action="address", address="어딘가 새 주소 1").status_code == 409   # 출고됨

    assert act(client, ids["ready"], action="option", option="진청, 30").status_code == 409             # 품절
    assert act(client, ids["ready"], action="option", option="빨강, 99").status_code == 422             # 없는 옵션
    assert act(client, ids["ready"], action="option", option="진청, 28").status_code == 200
    assert order(db, "R-1").product_name == "와이드 데님 팬츠 (진청, 28)"

    d = client.get(f"/api/inquiries/{ids['ready']}").json()
    assert any(e["text"].startswith("바로 처리 · 옵션 변경: 연청, 28 → 진청, 28") for e in d["history"])   # 처리 이력
    assert d["order"]["shipping_address"] == "경기 성남시 분당구 판교역로 166"
    assert {c["option"]: c["sold_out"] for c in d["order"]["option_choices"]}["진청, 30"] is True


def test_partial_cancel_and_duplicate_cancel(client, db, ids):
    login(client, "agent1")
    assert act(client, ids["ready"], action="partial_cancel", count=2).status_code == 422             # 전부는 티켓 승인으로
    assert act(client, ids["ready"], action="partial_cancel", count=1).status_code == 200
    o = order(db, "R-1")
    assert (o.quantity, o.amount, o.order_status) == (1, 49000, "상품 준비 중")
    assert db.query(Ticket).one().status == "승인"                                                      # 열린 취소 티켓도 처리됨

    assert client.get(f"/api/inquiries/{ids['ready']}").json()["order"]["duplicate_payment"] is True
    assert act(client, ids["ready"], action="duplicate_cancel").status_code == 200
    assert client.get(f"/api/inquiries/{ids['ready']}").json()["order"]["duplicate_payment"] is False
    assert act(client, ids["ready"], action="duplicate_cancel").status_code == 409                    # 두 번은 안 됨
    memos = [p.memo for p in db.query(Payment).filter(Payment.kind == "승인 취소")]
    assert "부분 취소 1개" in memos and "중복 승인 1건 취소 (승인번호 A2)" in memos


def test_points_and_coupon_limits(client, db, ids):
    login(client, "agent1")
    assert act(client, ids["shipped"], action="points", amount=5000).status_code == 403              # 상담원 한도 3,000원
    assert act(client, ids["shipped"], action="points", amount=3000, reason="배송 지연 사과").status_code == 200
    assert act(client, ids["shipped"], action="coupon", coupon="사과 쿠폰 5,000원").status_code == 403   # 관리자만
    assert act(client, ids["shipped"], action="coupon", coupon="사과 쿠폰 3,000원").status_code == 200
    login(client)
    assert act(client, ids["shipped"], action="points", amount=5000).status_code == 200              # 관리자는 가능
    assert sum(p.amount for p in db.query(PointHistory)) == 8000
    assert db.query(Coupon).one().name == "사과 쿠폰 3,000원"


def test_return_request_window_and_ownership(client, db, ids):
    login(client, "agent1")
    r = act(client, ids["delivered"], action="return", reason="단순 변심")
    assert r.status_code == 200 and "6,000원" in r.json()["message"]
    assert act(client, ids["delivered"], action="return").status_code == 409                          # 이미 접수
    assert act(client, ids["old"], action="return", reason="단순 변심").status_code == 409             # 7일 지남
    assert act(client, ids["old"], action="return", reason="불량·오배송").status_code == 200            # 30일 안
    assert act(client, ids["notmine"], action="address", address="새 주소입니다 12").status_code == 409  # 문의 이메일 ≠ 주문자

    login(client)
    logs = client.get("/api/audit-logs?group=문의 처리").json()["items"]
    assert any(x["label"] == "바로 처리" and x["summary"].startswith("반품 회수 접수") for x in logs)
    assert db.query(AdminAuditLog).filter_by(action="order_action").count() == 2
