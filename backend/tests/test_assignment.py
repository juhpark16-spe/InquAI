"""상담원 자동 배정 테스트: 담당 유형 → 전체 담당 → 미배정, 미처리가 적은 사람 우선."""

from sqlalchemy import select

from backend.core.security import hash_password
from backend.database.models import AdminAuditLog, AdminUser
from backend.tests.conftest import TEST_PASSWORD
from backend.tests.test_inquiries import ai, post, route_reply, saved  # noqa: F401  (ai 는 fixture)

AGENT1 = 2  # conftest: agent1, 담당 유형 없음 = 전체 담당


def add_agent(db, username, categories, active=True, role="agent"):
    u = AdminUser(username=username, role=role, display_name=username, categories=categories,
                  password_hash=hash_password("x"), is_active=active)
    db.add(u)
    db.commit()
    return u.id


def escalate(client, ai, category, content="벌써 몇 번째인데 아직도 처리가 안 됐어요"):
    """규칙(긴급도 높음)으로 담당자 연결되는 문의 등록"""
    ai["analyzer"].next = {"category": category, "urgency": "높음"}
    return post(client, content=content).json()["inquiry_number"]


def test_specialist_first(client, db, ai):
    refund = add_agent(db, "refund", ["반품·환불", "결제"])
    add_agent(db, "ship", ["배송"])
    inquiry, _ = saved(db, escalate(client, ai, "반품·환불"))
    assert inquiry.status == "담당자 처리" and inquiry.assigned_to == refund


def test_least_open_wins(client, db, ai):
    a = add_agent(db, "ship_a", ["배송"])
    b = add_agent(db, "ship_b", ["배송"])
    first, _ = saved(db, escalate(client, ai, "배송"))
    second, _ = saved(db, escalate(client, ai, "배송"))
    third, _ = saved(db, escalate(client, ai, "배송"))
    assert [first.assigned_to, second.assigned_to, third.assigned_to] == [a, b, a]


def test_fallback_to_generalist(client, db, ai):
    add_agent(db, "ship", ["배송"])
    inquiry, _ = saved(db, escalate(client, ai, "결제"))
    assert inquiry.assigned_to == AGENT1  # 결제 담당이 없어 전체 담당에게


def test_unassigned_when_nobody_fits(client, db, ai):
    agent1 = db.get(AdminUser, AGENT1)
    agent1.categories = ["상품"]
    db.commit()
    inquiry, _ = saved(db, escalate(client, ai, "결제"))
    assert inquiry.assigned_to is None  # 관리자가 직접 배정


def test_inactive_and_admin_are_skipped(client, db, ai):
    add_agent(db, "retired", ["결제"], active=False)
    add_agent(db, "boss", ["결제"], role="admin")
    inquiry, _ = saved(db, escalate(client, ai, "결제"))
    assert inquiry.assigned_to == AGENT1


def test_review_waiting_is_assigned(client, db, ai):
    ai["llm"].replies = {"route": route_reply("답변 초안", "배송 조회")}
    inquiry, _ = saved(db, post(client, content="제 주문 어디쯤 왔나요?").json()["inquiry_number"])
    assert inquiry.status == "검토 대기" and inquiry.assigned_to == AGENT1


def test_auto_answer_is_not_assigned(client, db, ai):
    ai["llm"].replies = {"route": route_reply("자동 답변", "FAQ 검색", ["F05"]),
                         "answer": {"answer": "1~3일입니다.", "used_faq_ids": ["F05"], "grounded": True}}
    inquiry, _ = saved(db, post(client).json()["inquiry_number"])
    assert inquiry.status == "자동 처리" and inquiry.assigned_to is None


def test_auto_assign_is_logged(client, db, ai):
    escalate(client, ai, "교환")
    log = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "auto_assign"))
    assert log.admin_id is None and log.detail["assigned_to"] == AGENT1 and log.detail["rule"] == "전체 담당"


def test_assigned_agent_sees_it(client, db, ai):
    number = escalate(client, ai, "배송")
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": "agent1", "password": TEST_PASSWORD})
    assert [i["inquiry_number"] for i in client.get("/api/inquiries").json()["items"]] == [number]


# ---- 계정 관리 API의 담당 유형 ----
def login_admin(client):
    client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_user_categories_api(client, db):
    h = login_admin(client)
    r = client.post("/api/admin/users", headers=h, json={"username": "agent9", "display_name": "상담원9",
                                                         "password": "pass-word-1", "categories": ["결제", "배송", "배송"]})
    assert r.status_code == 201 and r.json()["categories"] == ["배송", "결제"]  # 중복 제거, 유형 순서
    uid = r.json()["id"]
    assert client.patch(f"/api/admin/users/{uid}", headers=h, json={"categories": []}).json()["categories"] == []
    assert client.patch(f"/api/admin/users/{uid}", headers=h, json={"categories": ["없는유형"]}).status_code == 422
    assert client.get("/api/admin/users").json()[0]["categories"] == []  # 예전 계정(값 없음)도 빈 목록
