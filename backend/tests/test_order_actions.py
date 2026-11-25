"""문의 상세의 바로 처리: 조건이 맞을 때만 처리되고, 결과가 주문·결제·적립금·쿠폰·기록에 남는지."""

from datetime import timedelta

import pytest

from backend.database.models import (AdminAuditLog, Coupon, Customer, Inquiry, Order, Payment, PointHistory, ProductOption,
                                     Ticket, utcnow)
from backend.services import inventory
from backend.tests.conftest import TEST_PASSWORD

EMAIL = "park@example.com"
AGENT = 2


def login(client, username="admin"):
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")


@pytest.fixture()
def ids(db):
    inventory.ensure_catalog(db)   # 상품 옵션·재고 (데님 진청 30 품절, 진청 28 재고 7, 연청 28 재고 9)
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


def stock(db, option, product="와이드 데님 팬츠"):
    db.expire_all()
    return db.query(ProductOption).filter_by(product=product, option=option).one().stock


def test_address_and_option_only_before_shipping(client, db, ids):
    login(client, "agent1")
    assert act(client, ids["ready"], action="address", address="경기 성남시 분당구 판교역로 166").status_code == 200
    assert order(db, "R-1").shipping_address == "경기 성남시 분당구 판교역로 166"
    assert act(client, ids["shipped"], action="address", address="어딘가 새 주소 1").status_code == 409   # 출고됨

    assert act(client, ids["ready"], action="option", option="진청, 30").status_code == 409             # 품절
    assert act(client, ids["ready"], action="option", option="빨강, 99").status_code == 422             # 없는 옵션
    db.query(ProductOption).filter_by(product="와이드 데님 팬츠", option="진청, 28").one().stock = 1
    db.commit()
    r = act(client, ids["ready"], action="option", option="진청, 28")
    assert r.status_code == 409 and "재고 1개뿐" in r.json()["detail"]                       # 주문 수량 2개 > 재고
    db.query(ProductOption).filter_by(product="와이드 데님 팬츠", option="진청, 28").one().stock = 7
    db.commit()
    assert act(client, ids["ready"], action="option", option="진청, 28").status_code == 200
    assert order(db, "R-1").product_name == "와이드 데님 팬츠 (진청, 28)"
    assert (stock(db, "진청, 28"), stock(db, "연청, 28")) == (5, 11)                          # 재고 이동 (수량 2개)

    d = client.get(f"/api/inquiries/{ids['ready']}").json()
    assert any(e["text"].startswith("바로 처리 · 옵션 변경: 연청, 28 → 진청, 28") for e in d["history"])   # 처리 이력
    assert d["order"]["shipping_address"] == "경기 성남시 분당구 판교역로 166"
    choices = {c["option"]: c for c in d["order"]["option_choices"]}
    assert choices["진청, 30"]["sold_out"] is True and choices["진청, 30"]["restock_at"]      # 품절 + 재입고 예정일
    assert choices["진청, 28"]["current"] is True and choices["연청, 30"]["low"] is True       # 재고 3개 = 적음


def test_partial_cancel_and_duplicate_cancel(client, db, ids):
    login(client, "agent1")
    assert act(client, ids["ready"], action="partial_cancel", count=2).status_code == 422             # 전부는 티켓 승인으로
    assert act(client, ids["ready"], action="partial_cancel", count=1).status_code == 200
    o = order(db, "R-1")
    assert (o.quantity, o.amount, o.order_status) == (1, 49000, "상품 준비 중")
    assert stock(db, "연청, 28") == 10                                                          # 취소한 1개는 재고로
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


def test_cancel_ticket_restocks_and_draft_sees_stock(client, db, ids):
    """취소 티켓 승인 → 주문 수량만큼 재고로, AI 초안 입력에 같은 상품 옵션 재고가 들어감"""
    from backend.agents.drafting import build_input

    text = build_input(db, db.get(Inquiry, ids["ready"]), [], None)
    assert "같은 상품 옵션 재고: 연청, 26 재고 5개" in text and "진청, 30 품절 (재입고 예정" in text

    login(client, "agent1")
    ticket = db.query(Ticket).one()
    assert client.patch(f"/api/tickets/{ticket.id}", json={"status": "승인"}).status_code == 200
    assert order(db, "R-1").order_status == "취소"
    assert stock(db, "연청, 28") == 11                                                          # 2개 모두 재고로


def test_refund_ticket_once_with_return_fee(client, db, ids):
    """환불 티켓 승인: 단순 변심 반품이면 왕복 배송비 6,000원 차감, 두 번째 승인·취소된 주문은 409"""
    login(client, "agent1")
    assert act(client, ids["delivered"], action="return", reason="단순 변심").status_code == 200
    d1 = db.query(Order).filter_by(order_number="D-1").one()
    t1 = Ticket(inquiry_id=ids["delivered"], order_id=d1.id, ticket_type="환불", reason="환불", status="접수")
    t2 = Ticket(inquiry_id=ids["delivered"], order_id=d1.id, ticket_type="환불", reason="또 환불", status="접수")
    db.add_all([t1, t2])
    db.commit()
    card = client.get(f"/api/inquiries/{ids['delivered']}").json()["order"]           # 승인 확인창에 보일 금액·사유
    assert card["return_reason"] == "단순 변심" and card["refund_preview"] == 79000 - 6000
    assert client.patch(f"/api/tickets/{t1.id}", json={"status": "승인"}).status_code == 200
    refund = db.query(Payment).filter_by(order_id=d1.id, kind="환불").one()
    assert refund.amount == 79000 - 6000 and "6,000원 차감" in refund.memo
    r = client.patch(f"/api/tickets/{t2.id}", json={"status": "승인"})
    assert r.status_code == 409 and r.json()["code"] == "ALREADY_REFUNDED"


def test_duplicate_warning_stays_cleared_after_partial_and_full_cancel(client, db, ids):
    """부분 취소 → 중복 승인 취소 → 전체 취소 순서여도 정리된 중복 결제 경고가 다시 뜨지 않음"""
    login(client, "agent1")
    assert act(client, ids["ready"], action="partial_cancel", count=1).status_code == 200
    assert act(client, ids["ready"], action="duplicate_cancel").status_code == 200
    db.add(Ticket(inquiry_id=ids["ready"], order_id=order(db, "R-1").id, ticket_type="취소", reason="전부 취소", status="접수"))
    db.commit()
    t = db.query(Ticket).filter_by(status="접수").one()
    assert client.patch(f"/api/tickets/{t.id}", json={"status": "승인"}).status_code == 200
    assert client.get(f"/api/inquiries/{ids['ready']}").json()["order"]["duplicate_payment"] is False


def test_partial_cancel_deducts_shipping_under_30000(client, db, ids):
    """무료배송(3만원 이상) 주문이 부분 취소로 3만원 미만이 되면 배송비 3,000원을 빼고 환불 (정책 F28)"""
    o = order(db, "R-1")
    o.amount = 50000                                   # 2개 × 25,000원
    db.commit()
    login(client, "agent1")
    assert act(client, ids["ready"], action="partial_cancel", count=1).status_code == 200
    p = db.query(Payment).filter(Payment.kind == "승인 취소").one()
    assert p.amount == 22000 and "배송비 3,000원 차감" in p.memo        # 25,000 - 3,000
    assert order(db, "R-1").amount == 25000


def test_refund_fee_waived_when_inspection_finds_defect(client, db, ids):
    """회수 접수는 단순 변심이었지만 검수 결과 불량 → 체크하면 배송비 차감 없이 전액 (처리 이력에 남음)"""
    login(client, "agent1")
    assert act(client, ids["delivered"], action="return", reason="단순 변심").status_code == 200
    d1 = db.query(Order).filter_by(order_number="D-1").one()
    t = Ticket(inquiry_id=ids["delivered"], order_id=d1.id, ticket_type="환불", reason="환불", status="접수")
    db.add(t)
    db.commit()
    assert client.patch(f"/api/tickets/{t.id}", json={"status": "승인", "waive_return_fee": True}).status_code == 200
    refund = db.query(Payment).filter_by(order_id=d1.id, kind="환불").one()
    assert refund.amount == 79000 and "배송비 차감 안 함" in refund.memo
    history = [e["text"] for e in client.get(f"/api/inquiries/{ids['delivered']}").json()["history"]]
    assert any("환불 예정 79,000원 (검수 결과 불량으로 배송비 차감 안 함)" in h for h in history)


def test_option_change_resolves_open_cancel_request(client, db, ids):
    """색상·사이즈를 잘못 골라 들어온 취소 요청: [옵션 변경]으로 해결하면 그 취소 요청도 처리됨 (승인 대기에 남지 않게)"""
    login(client, "agent1")
    assert act(client, ids["ready"], action="option", option="진청, 28").status_code == 200
    t = db.query(Ticket).filter_by(inquiry_id=ids["ready"], ticket_type="취소").one()
    db.refresh(t)
    assert t.status == "승인" and "옵션 변경" in t.memo
    assert order(db, "R-1").order_status == "상품 준비 중"                    # 주문은 취소되지 않음
