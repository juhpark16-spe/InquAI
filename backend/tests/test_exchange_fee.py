"""단순 변심 교환 배송비 받기 (backend/services/exchange_fee.py): 적립금 차감 / 결제 요청 → 고객 결제, 기한·중복·본인 확인."""

from datetime import timedelta

from sqlalchemy import select

from backend.agents.drafting import build_input
from backend.core.security import hash_password
from backend.database.models import Customer, Inquiry, Payment, PointHistory, utcnow
from backend.tests.test_order_actions import EMAIL, act, ids, login, order  # noqa: F401  (fixture 재사용)

SHOP_PW = "shop-password-1234"
LOOKUP_PW = "lookup-pass-123"


def fee_rows(db, number):
    o = order(db, number)
    return [p for p in o.payments if p.kind == "추가 결제"]


def test_request_then_customer_pays(client, db, ids):
    login(client, "agent1")
    r = act(client, ids["delivered"], action="exchange_fee", method="request")
    assert r.status_code == 200 and "결제 요청" in r.json()["message"]
    assert act(client, ids["delivered"], action="exchange_fee", method="request").status_code == 409   # 두 번 요청 안 됨
    card = client.get(f"/api/inquiries/{ids['delivered']}").json()["order"]
    assert card["exchange_fee"]["status"] == "요청" and card["exchange_fee"]["amount"] == 6000

    # 회원: 내 문의에 [교환 배송비 결제] → 결제
    c = db.scalar(select(Customer).where(Customer.email == EMAIL))
    c.password_hash = hash_password(SHOP_PW)
    db.commit()
    client.cookies.clear()
    assert client.post("/api/shop/login", json={"email": EMAIL, "password": SHOP_PW}).status_code == 200
    client.headers["X-Shop-CSRF"] = client.cookies.get("shop_csrf")
    item = next(i for i in client.get("/api/shop/inquiries").json()["items"] if i["inquiry_number"] == "INQ-A-delivered")
    assert item["exchange_fee"]["status"] == "요청"
    assert client.post("/api/shop/inquiries/INQ-A-delivered/exchange-fee", json={"method": "현금"}).status_code == 422
    r = client.post("/api/shop/inquiries/INQ-A-delivered/exchange-fee", json={"method": "신용카드"})
    assert r.status_code == 200 and r.json()["exchange_fee"]["status"] == "완료"
    assert client.post("/api/shop/inquiries/INQ-A-delivered/exchange-fee", json={"method": "신용카드"}).status_code == 409
    [row] = fee_rows(db, "D-1")
    assert (row.status, row.method, row.amount) == ("완료", "신용카드", 6000) and row.approval_no


def test_points_need_balance(client, db, ids):
    login(client, "agent1")
    r = act(client, ids["delivered"], action="exchange_fee", method="points")
    assert r.status_code == 409 and "적립금이 부족" in r.json()["detail"]
    c = db.scalar(select(Customer).where(Customer.email == EMAIL))
    db.add(PointHistory(customer_id=c.id, amount=10000, reason="구매 적립", at=utcnow()))
    db.commit()
    r = act(client, ids["delivered"], action="exchange_fee", method="points")
    assert r.status_code == 200 and "10,000원 → 4,000원" in r.json()["message"]
    db.expire_all()
    assert sum(p.amount for p in db.scalars(select(PointHistory).where(PointHistory.customer_id == c.id))) == 4000
    assert [(p.status, p.method) for p in fee_rows(db, "D-1")] == [("완료", "적립금")]
    assert act(client, ids["delivered"], action="exchange_fee", method="points").status_code == 409        # 이미 받음


def test_window_and_state(client, db, ids):
    login(client, "agent1")
    r = act(client, ids["old"], action="exchange_fee", method="request")       # 배송 완료 12일 → 단순 변심 7일 지남
    assert r.status_code == 409 and "7일" in r.json()["detail"]
    assert act(client, ids["shipped"], action="exchange_fee", method="request").status_code == 409    # 아직 배송 중
    assert act(client, ids["delivered"], action="exchange_fee", method="cash").status_code == 422


def test_guest_pays_with_lookup_password(client, db, ids):
    i = db.get(Inquiry, ids["delivered"])
    i.lookup_password_hash = hash_password(LOOKUP_PW)
    db.commit()
    login(client, "agent1")
    assert act(client, ids["delivered"], action="exchange_fee", method="request").status_code == 200
    client.cookies.clear()
    body = {"customer_email": EMAIL, "password": LOOKUP_PW, "inquiry_number": "INQ-A-delivered", "method": "간편결제"}
    assert client.post("/api/inquiries/exchange-fee", json={**body, "password": "wrong-pass-1"}).status_code == 404
    r = client.post("/api/inquiries/exchange-fee", json=body)
    assert r.status_code == 200 and r.json()["exchange_fee"]["method"] == "간편결제"


def test_draft_input_knows_fee_state(client, db, ids):
    login(client, "agent1")
    act(client, ids["delivered"], action="exchange_fee", method="request")
    db.expire_all()
    text = build_input(db, db.get(Inquiry, ids["delivered"]), [], None)
    assert "교환 배송비 6,000원: 고객 결제 대기" in text
    assert "교환 배송비:" in text.split("[정책]")[1]       # 답변 문구(정책)에 받는 방법
    o = order(db, "D-1")
    assert db.scalar(select(Payment).where(Payment.order_id == o.id, Payment.kind == "승인")) is None   # 승인 줄과 섞이지 않음
