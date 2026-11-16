"""시연 데이터(seed_demo)가 화면이 쓰는 API에서 그대로 보이는지 확인"""

from datetime import timedelta

from sqlalchemy import func, select

from backend.database import seed_data
from backend.database.models import AdminUser, Inquiry, Response
from backend.database.models import Order, as_utc
from backend.database.seed_data import PRODUCTS
from backend.database.seed_demo import DEMO_LOOKUP_PASSWORD, product_kind, seed_inquiries, short_name
from backend.tests.conftest import TEST_PASSWORD


def login(client, username="admin"):
    r = client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")


def seeded(db):
    seed_data.seed_faqs(db)
    seed_data.seed_orders(db, reset=False)
    db.flush()
    n = seed_inquiries(db)
    db.commit()
    return n


def test_seed_is_repeatable_and_consistent(db):
    n = seeded(db)
    assert n == db.scalar(select(func.count()).select_from(Inquiry)) > 30
    numbers = db.scalars(select(Inquiry.inquiry_number)).all()
    assert len(set(numbers)) == len(numbers)                     # 문의 번호 중복 없음
    statuses = set(db.scalars(select(Inquiry.status)))
    assert {"자동 처리", "완료"} <= statuses and statuses & {"검토 대기", "담당자 처리"}   # 처리된 것과 미처리가 섞임
    agent = db.scalar(select(AdminUser).where(AdminUser.username == "agent1"))
    open_rows = db.scalars(select(Inquiry).where(Inquiry.status.in_(("검토 대기", "담당자 처리")))).all()
    assert all(i.assigned_to == agent.id for i in open_rows if i.assigned_to)   # 사람이 볼 문의는 상담원에게
    sent = db.scalars(select(Response).where(Response.status == "발송")).all()
    assert any(r.rating == 1 for r in sent)                     # 고객 평가가 일부 있음
    assert all(r.approved_at >= r.inquiry.created_at for r in sent)
    assert all(i.updated_at >= i.created_at - timedelta(seconds=1) for i in db.scalars(select(Inquiry)))


def test_dashboard_and_lookup_show_demo_data(client, db):
    seeded(db)
    login(client)
    s = client.get("/api/stats/summary").json()
    assert s["kpi"]["total"] > s["previous"]["total"] > 0      # 지난주 대비 증감이 보임
    assert s["previous"]["auto_rate"] is not None
    assert s["now"]["open"] > 0
    assert s["ratings"]["ai"]["up"] + s["ratings"]["agent"]["up"] > 0
    assert len(client.get("/api/stats/activity").json()) == 8

    done = db.scalar(select(Inquiry).where(Inquiry.status == "완료"))
    detail = client.get(f"/api/inquiries/{done.id}").json()
    kinds = [h["kind"] for h in detail["history"]]
    assert kinds[0] == "received" and "sent" in kinds

    r = client.post("/api/inquiries/lookup", json={"customer_email": done.customer_email, "password": DEMO_LOOKUP_PASSWORD})
    assert r.status_code == 200
    assert done.inquiry_number in [i["inquiry_number"] for i in r.json()["items"]]


def test_inquiry_text_matches_ordered_product(db):
    assert all(product_kind(name) for name, _ in PRODUCTS)           # 모든 모의 상품에 종류가 있음
    seeded(db)
    with_order = db.scalars(select(Inquiry).where(Inquiry.order_number.is_not(None))).all()
    assert with_order
    for i in with_order:
        order = db.scalar(select(Order).where(Order.order_number == i.order_number))
        assert order.customer.email == i.customer_email              # 본인 주문
        assert short_name(order.product_name) in i.content, (i.content, order.product_name)
        assert as_utc(order.ordered_at) < as_utc(i.created_at)            # 주문한 뒤에 문의함
        if order.delivered_at:
            assert as_utc(order.delivered_at) < as_utc(i.created_at)
    broken = [i.content for i in with_order if "불량" in i.title or "불량 같" in i.content]
    assert not any("전원" in t and "이어폰" not in t for t in broken)  # 이불에 "전원이 안 켜져요" 같은 문장 없음
