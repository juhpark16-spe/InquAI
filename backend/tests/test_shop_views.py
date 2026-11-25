"""관리 화면의 조회 메뉴: 취소·교환·반품 요청 목록, 주문·배송, 고객 조회, 재고 현황.
상담원은 내가 맡은 문의의 것만 보이고, 고객 정보를 열면 작업 기록이 남는다."""

from datetime import timedelta

from sqlalchemy import select

from backend.database.models import AdminAuditLog, Customer, Order, Payment, ProductOption, Ticket, utcnow
from backend.tests.test_inquiry_context import login, setup  # noqa: F401  (setup 은 fixture)


def add_tickets(db, setup):
    a2 = db.scalar(select(Order).where(Order.order_number == "A-2"))
    db.add_all([
        Ticket(inquiry_id=setup["main"], ticket_type="환불", reason="반품 후 환불"),                       # 상담원1 담당
        Ticket(inquiry_id=setup["other"], order_id=a2.id, ticket_type="취소", reason="출고 전 취소"),     # 미배정
        Ticket(inquiry_id=setup["other"], ticket_type="교환", reason="사이즈 교환", status="반려", memo="기한 지남"),
    ])
    db.commit()


def test_ticket_list_admin(client, db, setup):
    add_tickets(db, setup)
    login(client)
    r = client.get("/api/tickets").json()            # 기본: 승인 대기(접수)
    assert r["counts"] == {"접수": 2, "승인": 0, "반려": 1} and r["total"] == 2
    cancel = next(t for t in r["items"] if t["ticket_type"] == "취소")
    assert cancel["order"]["order_number"] == "A-2" and cancel["inquiry"]["inquiry_number"] == "INQ-9"
    assert client.get("/api/tickets", params={"status": "all", "ticket_type": "교환"}).json()["items"][0]["memo"] == "기한 지남"


def test_ticket_list_agent_sees_own(client, db, setup):
    add_tickets(db, setup)
    login(client, "agent1")
    r = client.get("/api/tickets", params={"status": "all"}).json()
    assert [t["inquiry"]["inquiry_number"] for t in r["items"]] == ["INQ-1"]


def test_customer_search_and_detail(client, db, setup):
    login(client)
    for q in ("김민준", "kim@", "0000", "A-2"):     # 이름·이메일·전화 뒷자리·주문번호
        assert client.get("/api/customers", params={"q": q}).json()["total"] == 1, q
    item = client.get("/api/customers").json()["items"][0]
    assert item["orders"] == 2 and item["inquiries"] == 2 and item["open_inquiries"] == 1 and item["phone"] == "010-****-0000"
    d = client.get(f"/api/customers/{item['id']}").json()
    assert [o["order_number"] for o in d["orders"]] == ["A-2", "A-1"] and d["orders"][0]["cancellable"] is True
    assert {i["inquiry_number"] for i in d["inquiries"]} == {"INQ-1", "INQ-0"}
    log = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "customer_view"))
    assert log.target_type == "customer" and log.target_id == item["id"]
    audit = client.get("/api/audit-logs").json()["items"][0]
    assert audit["label"] == "고객 정보 조회" and audit["target"]["label"] == "김민준"
    # 문의 상세의 고객 카드 → [고객 정보 전체 보기] 링크용 번호
    assert client.get(f"/api/inquiries/{setup['main']}").json()["customer_profile"]["customer_id"] == item["id"]


def test_customer_agent_scope(client, db, setup):
    other = Customer(name="남", email="other@example.com", phone="010-1111-2222")
    db.add(other)
    db.commit()
    login(client, "agent1")
    names = [c["name"] for c in client.get("/api/customers").json()["items"]]
    assert names == ["김민준"]                                         # 내가 맡은 문의(INQ-1)의 고객만
    assert client.get(f"/api/customers/{other.id}").status_code == 404
    mine = db.scalar(select(Customer).where(Customer.name == "김민준"))
    d = client.get(f"/api/customers/{mine.id}").json()
    assert d["inquiry_total"] == 2 and [i["inquiry_number"] for i in d["inquiries"]] == ["INQ-1"]   # 남이 맡은 문의는 건수만


def test_inventory(client, db, setup):
    # 기본 재고표(서버 시작 때 채움)와 겹치지 않는 시험 상품으로
    db.add_all([ProductOption(product="시험 데님", option="연청, 28", stock=0),
                ProductOption(product="시험 데님", option="연청, 30", stock=2),
                ProductOption(product="시험 니트", option="아이보리", stock=12)])
    db.commit()
    login(client, "agent1")
    r = client.get("/api/inventory", params={"q": "시험"}).json()
    assert r["summary"] == {"options": 3, "sold_out": 1, "low": 1}
    only = client.get("/api/inventory", params={"q": "시험", "only": "sold_out"}).json()["products"]
    assert only == [{"product": "시험 데님", "options": [{"option": "연청, 28", "stock": 0, "sold_out": True, "low": False,
                                                         "restock_at": None}]}]


def test_refunds(client, db, setup):
    a1 = db.scalar(select(Order).where(Order.order_number == "A-1"))   # 상담원1 담당 문의(INQ-1)의 주문
    a2 = db.scalar(select(Order).where(Order.order_number == "A-2"))   # 미배정 문의(INQ-9)의 주문
    now = utcnow()
    db.add_all([
        Payment(order_id=a1.id, kind="승인", method="신용카드", amount=39000, at=now - timedelta(days=9)),          # 환불 아님
        Payment(order_id=a1.id, kind="환불", status="예정", method="신용카드", amount=33000, at=now - timedelta(days=1)),  # 예정일 지남
        Payment(order_id=a2.id, kind="환불", status="예정", method="계좌이체", amount=45000, at=now + timedelta(days=2)),
        Payment(order_id=a2.id, kind="승인 취소", method="계좌이체", amount=10000, at=now - timedelta(days=3)),
    ])
    db.commit()
    login(client)
    r = client.get("/api/tickets/refunds").json()       # 기본: 예정 (예정일 가까운 것부터)
    assert r["summary"] == {"pending": 2, "pending_amount": 78000, "overdue": 1, "done": 1} and r["total"] == 2
    assert [(i["amount"], i["overdue"]) for i in r["items"]] == [(33000, True), (45000, False)]
    first = r["items"][0]
    assert first["inquiry"]["inquiry_number"] == "INQ-1" and first["customer_name"] == "김민준" and first["order"]["order_number"] == "A-1"
    assert [i["kind"] for i in client.get("/api/tickets/refunds", params={"state": "완료"}).json()["items"]] == ["승인 취소"]
    login(client, "agent1")
    mine = client.get("/api/tickets/refunds", params={"state": "all"}).json()
    assert [i["order"]["order_number"] for i in mine["items"]] == ["A-1"] and mine["summary"]["pending"] == 1


def test_orders(client, db, setup):
    other = Customer(name="남", email="other@example.com", phone="010-1111-2222")
    db.add(other)
    db.flush()
    db.add(Order(customer_id=other.id, order_number="B-1", product_name="패딩", amount=89000, order_status="배송 중",
                 shipping_status="옥천 HUB 출발", ordered_at=utcnow() - timedelta(days=6)))   # 출고 6일째 → 배송 지연
    db.commit()
    login(client)
    r = client.get("/api/orders").json()
    assert r["counts"] == {"ready": 1, "shipping": 1, "delayed": 1, "delivered": 1, "return": 0, "cancel": 0, "all": 3}
    assert [o["order_number"] for o in r["items"]] == ["A-2", "A-1", "B-1"]      # 최근 주문부터
    a1 = r["items"][1]
    assert a1["customer"]["name"] == "김민준" and a1["inquiries"] == 1 and a1["latest_inquiry"]["inquiry_number"] == "INQ-1"
    delayed = client.get("/api/orders", params={"group": "delayed"}).json()["items"]
    assert [(o["order_number"], o["delayed"]) for o in delayed] == [("B-1", True)]
    assert client.get("/api/orders", params={"q": "맨투맨"}).json()["total"] == 1
    d = client.get("/api/orders/A-1").json()
    assert d["order"]["order_number"] == "A-1" and d["order"]["returnable"] is True and d["customer"]["name"] == "김민준"
    assert [i["inquiry_number"] for i in d["inquiries"]] == ["INQ-1"]
    # 상담원1: 내가 맡은 문의(INQ-1)의 고객 주문만
    login(client, "agent1")
    assert [o["order_number"] for o in client.get("/api/orders").json()["items"]] == ["A-2", "A-1"]
    assert client.get("/api/orders/B-1").status_code == 404


def test_carrier_info_and_driver(client, db, setup):
    """주문 정보의 택배사 확인: 대표번호·배송조회 주소(송장번호 숫자만), '배송 출발' 뒤 담당 기사(연락처 가림).
    AI 초안 입력에는 기사 정보가 들어가지 않음"""
    from backend.agents.drafting import build_input
    from backend.database.models import Inquiry, ShipmentEvent, utcnow
    a1 = db.scalar(select(Order).where(Order.order_number == "A-1"))
    a1.carrier, a1.tracking_number = "CJ대한통운", "6901-2345-6789"
    db.commit()
    login(client)
    card = client.get(f"/api/inquiries/{setup['main']}").json()["order"]
    assert card["carrier_info"]["phone"] == "1588-1255" and card["carrier_info"]["tracking_url"].endswith("wblNo=690123456789")
    assert card["driver"] is None                                           # 아직 배송 출발 단계 없음
    db.add(ShipmentEvent(order_id=a1.id, at=utcnow(), status="배송 출발", location="담당 기사 배정"))
    db.commit()
    driver = client.get(f"/api/inquiries/{setup['main']}").json()["order"]["driver"]
    assert driver["name"].endswith("기사") and driver["phone"].startswith("010-****-")
    assert client.get(f"/api/orders/A-1").json()["order"]["driver"] == driver      # 주문·배송 화면도 같은 기사
    assert driver["name"] not in build_input(db, db.get(Inquiry, setup["main"]), [], None)
