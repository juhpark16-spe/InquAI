"""쇼핑몰 로그인 연동 시연 (고객 로그인) 테스트: 로그인·잠금, 내 주문·문의, 로그인 고객의 문의 등록·추가 문의·평가,
관리자 로그인과 분리, 비회원 문의는 그대로."""

from datetime import timedelta

import pytest

from backend.core.security import hash_password
from backend.database.models import Customer, Inquiry, Order, Response, utcnow
from backend.tests.test_inquiries import PW, ai, post, route_reply  # noqa: F401  (ai: 가짜 분류기·LLM 고정물)

SHOP_PW = "shop-pass-1234"


@pytest.fixture()
def shop(client, db, ai):  # noqa: F811
    me = db.query(Customer).filter_by(email="customer01@example.com").one()
    me.password_hash = hash_password(SHOP_PW)
    other = Customer(name="이서연", email="customer02@example.com", phone="010-1111-1111",
                     password_hash=hash_password(SHOP_PW))
    db.add(other)
    db.flush()
    db.add(Order(customer_id=other.id, order_number="20261110-0002", product_name="코트", amount=99000,
                 order_status="배송 완료", shipping_status="배송 완료", ordered_at=utcnow() - timedelta(days=5)))
    db.commit()
    ai["llm"].replies = {"route": route_reply("자동 답변", "FAQ 검색", ["F05"]),
                         "answer": {"answer": "보통 1~3일 안에 도착합니다.", "used_faq_ids": ["F05"], "grounded": True}}
    return ai


def login(client, email="customer01@example.com", password=SHOP_PW):
    return client.post("/api/shop/login", json={"email": email, "password": password})


def shop_csrf(client):
    return {"X-Shop-CSRF": client.cookies.get("shop_csrf")}


def test_login_me_logout(client, shop):
    assert client.get("/api/shop/me").status_code == 401
    r = login(client, email=" Customer01@Example.com ")
    assert r.status_code == 200 and r.json() == {"name": "김민준", "email": "customer01@example.com"}
    assert client.get("/api/shop/me").json()["name"] == "김민준"
    assert client.post("/api/shop/logout").status_code == 204
    assert client.get("/api/shop/me").status_code == 401


def test_wrong_password_and_lock(client, shop):
    assert login(client, password="wrong").status_code == 401
    assert login(client, email="nobody@example.com").status_code == 401          # 없는 이메일도 같은 응답
    for _ in range(4):
        login(client, password="wrong")
    assert login(client).status_code == 429                                       # 5번 틀리면 맞아도 잠김


def test_customer_without_password_cannot_login(client, db, shop):
    db.add(Customer(name="박지훈", email="customer03@example.com", phone="010-2222-2222"))
    db.commit()
    assert login(client, email="customer03@example.com", password="").status_code == 422
    assert login(client, email="customer03@example.com", password="anything").status_code == 401


def test_my_orders_and_inquiries(client, shop):
    login(client)
    orders = client.get("/api/shop/orders").json()
    assert [o["order_number"] for o in orders] == ["20261110-0001"]                # 남의 주문(0002)은 안 보임

    r = client.post("/api/inquiries", headers=shop_csrf(client), json={
        "customer_name": "아무개", "customer_email": "someone@example.com", "title": "문의",
        "content": "배송 며칠 걸려요?", "privacy_agreed": True, "order_number": "20261110-0001"})
    assert r.status_code == 201, r.json()
    number = r.json()["inquiry_number"]
    mine = client.get("/api/shop/inquiries").json()["items"]
    assert [i["inquiry_number"] for i in mine] == [number]
    assert client.get("/api/shop/orders").json()[0]["inquiry_count"] == 1


def test_logged_in_inquiry_uses_account_and_own_orders_only(client, db, shop):
    login(client)
    r = client.post("/api/inquiries", headers=shop_csrf(client), json={
        "customer_name": "다른 이름", "customer_email": "fake@example.com", "title": "문의", "content": "배송 며칠 걸려요?",
        "privacy_agreed": True, "order_number": "20261110-0001"})
    assert r.status_code == 201
    inquiry = db.query(Inquiry).filter_by(inquiry_number=r.json()["inquiry_number"]).one()
    assert (inquiry.customer_name, inquiry.customer_email) == ("김민준", "customer01@example.com")
    assert inquiry.lookup_password_hash is None

    other = client.post("/api/inquiries", headers=shop_csrf(client), json={
        "customer_name": "김민준", "customer_email": "customer01@example.com", "title": "문의", "content": "배송 며칠?",
        "privacy_agreed": True, "order_number": "20261110-0002"})
    assert other.status_code == 422 and other.json()["code"] == "ORDER_NOT_FOUND"


def test_logged_in_post_needs_shop_csrf(client, shop):
    login(client)
    r = client.post("/api/inquiries", json={"customer_name": "a", "customer_email": "a@example.com", "title": "t",
                                            "content": "배송 며칠 걸려요?", "privacy_agreed": True})
    assert r.status_code == 403 and r.json()["code"] == "CSRF_FAILED"


def test_guest_inquiry_still_needs_lookup_password(client, shop):
    assert post(client, password=None).status_code == 422
    assert post(client).status_code == 201                                         # 비회원 + 조회 비밀번호


def test_follow_up_and_rating_without_lookup_password(client, db, shop):
    login(client)
    number = client.post("/api/inquiries", headers=shop_csrf(client), json={
        "customer_name": "x", "customer_email": "x@example.com", "title": "문의", "content": "배송 며칠 걸려요?",
        "privacy_agreed": True}).json()["inquiry_number"]
    answer = db.query(Response).join(Inquiry).filter(Inquiry.inquiry_number == number).one()

    r = client.post(f"/api/shop/answers/{answer.id}/rating", params={"inquiry_number": number},
                    json={"helpful": True}, headers=shop_csrf(client))
    assert r.status_code == 200 and r.json()["rating"] == 1
    r = client.post(f"/api/shop/inquiries/{number}/follow-up", json={"content": "주말에도 오나요?"},
                    headers=shop_csrf(client))
    assert r.status_code == 201

    # 다른 고객은 내 문의에 추가 문의를 쓸 수 없음
    client.post("/api/shop/logout")
    login(client, email="customer02@example.com")
    r = client.post(f"/api/shop/inquiries/{number}/follow-up", json={"content": "남의 문의"}, headers=shop_csrf(client))
    assert r.status_code == 404


def test_shop_and_admin_sessions_are_separate(client, shop):
    """고객 쿠키로 관리자 API를 쓸 수 없고, 관리자 로그인으로 고객 API를 쓸 수 없음"""
    login(client)
    assert client.get("/api/inquiries").status_code == 401                          # 관리자 문의 목록
    client.post("/api/shop/logout")
    assert client.post("/api/auth/login", json={"username": "admin", "password": "test-password-1234"}).status_code == 200
    assert client.get("/api/shop/me").status_code == 401
