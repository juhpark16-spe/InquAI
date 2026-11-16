"""문의 관리 API(목록·상세) 테스트: 필터·정렬·검색·페이지, 관리자/상담원 권한."""

from datetime import timedelta

import pytest

from backend.database.models import AgentLog, AnalysisResult, Inquiry, Ticket, utcnow
from backend.tests.conftest import TEST_PASSWORD

AGENT_ID = 2  # conftest: 1=admin, 2=agent1

# (번호 끝, 제목, 상태, 유형, 긴급도, 처리 방식, 배정, 몇 분 전)
ROWS = [
    ("0001", "배송 언제 와요", "자동 처리", "배송", "낮음", "자동 답변", None, 50),
    ("0002", "환불 아직도 안 됨", "담당자 처리", "반품·환불", "높음", "담당자 연결", AGENT_ID, 40),
    ("0003", "교환 신청", "검토 대기", "교환", "보통", "답변 초안", AGENT_ID, 30),
    ("0004", "쿠폰 100% 할인?", "자동 처리", "쿠폰·적립금·회원", "낮음", "자동 답변", None, 20),
    ("0005", "결제 두 번 됨", "담당자 처리", "결제", "높음", "담당자 연결", None, 10),
]


@pytest.fixture()
def inquiries(db):
    now = utcnow()
    for num, title, status, cat, urg, dec, assigned, minutes in ROWS:
        i = Inquiry(inquiry_number=f"INQ-20261115-{num}", customer_name="고객", title=title, content=f"{title} 내용",
                    customer_email=f"c{num}@example.com", status=status, assigned_to=assigned,
                    created_at=now - timedelta(minutes=minutes))
        db.add(i)
        db.flush()
        db.add(AnalysisResult(inquiry_id=i.id, category=cat, confidence=0.9, sentiment="중립",
                              sentiment_confidence=0.8, urgency=urg, route="FAQ형", decision=dec, decided_by="규칙",
                              decision_reason="테스트", model_version="test", scores={}))
        db.add(AgentLog(inquiry_id=i.id, category=cat, confidence=0.9, decision=dec, decided_by="규칙",
                        selected_tool="상담원 이관", tool_success=True, latency_ms=10))
        if dec == "담당자 연결":
            db.add(Ticket(inquiry_id=i.id, ticket_type="이관", reason="테스트"))
    db.add(Inquiry(inquiry_number="INQ-20261115-0006", customer_name="고객", title="분석 전", content="분석 전 문의",
                   customer_email="c0006@example.com", status="접수", created_at=now))
    db.commit()


def login(client, username):
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200


def numbers(r):
    return [item["inquiry_number"][-4:] for item in r.json()["items"]]


def test_requires_login(client, inquiries):
    assert client.get("/api/inquiries").status_code == 401
    assert client.get("/api/inquiries/1").status_code == 401


def test_admin_list_sorted_by_urgency(client, inquiries):
    login(client, "admin")
    r = client.get("/api/inquiries")
    assert r.status_code == 200 and r.json()["total"] == 6
    # 긴급도 높음 → 보통 → 낮음 → 분석 전, 같은 긴급도는 최신순
    assert numbers(r) == ["0005", "0002", "0003", "0004", "0001", "0006"]
    assert numbers(client.get("/api/inquiries", params={"sort": "-created_at"})) == \
        ["0006", "0005", "0004", "0003", "0002", "0001"]


def test_list_item_shape(client, inquiries):
    login(client, "admin")
    item = next(i for i in client.get("/api/inquiries").json()["items"] if i["inquiry_number"].endswith("0002"))
    assert item["assigned_to"] == {"id": AGENT_ID, "display_name": "상담원1"}
    assert (item["category"], item["urgency"], item["decision"]) == ("반품·환불", "높음", "담당자 연결")
    assert 0 <= item["confidence"] <= 1  # 목록에 AI 확신도


@pytest.mark.parametrize("params,expected", [
    ({"status": "자동 처리"}, ["0004", "0001"]),
    ({"category": "결제"}, ["0005"]),
    ({"urgency": "높음"}, ["0005", "0002"]),
    ({"decision": "답변 초안"}, ["0003"]),
    ({"assigned_to": "none"}, ["0005", "0004", "0001", "0006"]),
    ({"assigned_to": str(AGENT_ID)}, ["0002", "0003"]),
    ({"q": "환불"}, ["0002"]),
    ({"q": "c0003@"}, ["0003"]),        # 이메일 검색
    ({"q": "-0004"}, ["0004"]),          # 문의 번호 검색
    ({"q": "100%"}, ["0004"]),           # % 는 와일드카드가 아니라 글자로
    ({"q": "%"}, ["0004"]),
])
def test_filters(client, inquiries, params, expected):
    login(client, "admin")
    assert numbers(client.get("/api/inquiries", params=params)) == expected


def test_pagination(client, inquiries):
    login(client, "admin")
    r = client.get("/api/inquiries", params={"page": 2, "size": 4})
    assert r.json()["total"] == 6 and numbers(r) == ["0001", "0006"]
    assert client.get("/api/inquiries", params={"size": 101}).status_code == 422


@pytest.mark.parametrize("params", [{"category": "없는유형"}, {"status": "아무거나"}, {"assigned_to": "abc"}])
def test_invalid_params(client, inquiries, params):
    login(client, "admin")
    assert client.get("/api/inquiries", params=params).status_code == 422


def test_agent_sees_only_assigned(client, inquiries):
    login(client, "agent1")
    assert numbers(client.get("/api/inquiries")) == ["0002", "0003"]
    # 다른 배정 조건을 줘도 자신에게 배정된 것만
    assert numbers(client.get("/api/inquiries", params={"assigned_to": "none"})) == ["0002", "0003"]


def test_detail_admin(client, inquiries):
    login(client, "admin")
    r = client.get("/api/inquiries/2")
    assert r.status_code == 200
    d = r.json()
    assert d["inquiry_number"].endswith("0002") and d["customer"]["email"] == "c0002@example.com"
    assert d["analysis"]["decision"] == "담당자 연결" and d["analysis"]["urgency"] == "높음"
    assert len(d["agent_logs"]) == 1 and d["tickets"][0]["ticket_type"] == "이관"
    assert d["responses"] == [] and d["corrections"] == []
    assert d["created_at"].endswith("Z") and d["agent_logs"][0]["created_at"].endswith("Z")  # UTC 표시


def test_detail_before_analysis(client, inquiries):
    login(client, "admin")
    d = client.get("/api/inquiries/6").json()
    assert d["status"] == "접수" and d["analysis"] is None and d["agent_logs"] == []


def test_detail_permissions(client, inquiries):
    login(client, "agent1")
    assert client.get("/api/inquiries/2").status_code == 200        # 배정됨
    r = client.get("/api/inquiries/1")                                # 배정 안 됨
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"
    assert client.get("/api/inquiries/999").status_code == 404


# ---- 배정·상태 변경 ----------------------------------------------------------
def patch(client, url, body):
    return client.patch(url, json=body, headers={"X-CSRF-Token": client.cookies.get("csrf_token")})


def audit_rows(db):
    from sqlalchemy import select
    from backend.database.models import AdminAuditLog
    db.expire_all()
    return [(l.action, l.target_id, l.detail.get("before"), l.detail.get("after"))
            for l in db.scalars(select(AdminAuditLog).where(AdminAuditLog.target_type == "inquiry"))]


def test_assign_moves_review_to_agent(client, db, inquiries):
    login(client, "admin")
    r = patch(client, "/api/inquiries/5/assign", {"assigned_to": AGENT_ID})       # 담당자 처리 → 그대로
    assert r.status_code == 200 and r.json()["assigned_to"]["id"] == AGENT_ID and r.json()["status"] == "담당자 처리"
    r = patch(client, "/api/inquiries/6/assign", {"assigned_to": AGENT_ID})       # 접수 → 담당자 처리
    assert r.json()["status"] == "담당자 처리" and r.json()["updated_at"].endswith("Z")
    r = patch(client, "/api/inquiries/1/assign", {"assigned_to": AGENT_ID})       # 자동 처리 → 그대로
    assert r.json()["status"] == "자동 처리"

    rows = audit_rows(db)
    assert rows[1] == ("assign", 6, {"assigned_to": None, "status": "접수"},
                       {"assigned_to": AGENT_ID, "status": "담당자 처리"})

    # 배정되자 상담원 목록에 나타남
    client.cookies.clear()
    login(client, "agent1")
    assert set(numbers(client.get("/api/inquiries"))) == {"0001", "0002", "0003", "0005", "0006"}


def test_unassign(client, db, inquiries):
    login(client, "admin")
    r = patch(client, "/api/inquiries/2/assign", {"assigned_to": None})
    assert r.json()["assigned_to"] is None and r.json()["status"] == "담당자 처리"


def test_assign_same_is_not_logged(client, db, inquiries):
    login(client, "admin")
    assert patch(client, "/api/inquiries/2/assign", {"assigned_to": AGENT_ID}).status_code == 200
    assert audit_rows(db) == []


def test_assign_invalid_target(client, db, inquiries):
    from backend.core.security import hash_password
    from backend.database.models import AdminUser
    db.add(AdminUser(username="old", role="agent", display_name="퇴사", password_hash=hash_password("x"),
                     is_active=False))
    db.commit()
    login(client, "admin")
    assert patch(client, "/api/inquiries/1/assign", {"assigned_to": 999}).json()["code"] == "INVALID_ASSIGNEE"
    assert patch(client, "/api/inquiries/1/assign", {"assigned_to": 3}).status_code == 400   # 비활성 계정
    assert patch(client, "/api/inquiries/999/assign", {"assigned_to": AGENT_ID}).status_code == 404


def test_agent_cannot_assign(client, inquiries):
    login(client, "agent1")
    r = patch(client, "/api/inquiries/2/assign", {"assigned_to": AGENT_ID})
    assert r.status_code == 403 and r.json()["code"] == "FORBIDDEN"


def test_patch_requires_csrf(client, inquiries):
    login(client, "admin")
    assert client.patch("/api/inquiries/1/assign", json={"assigned_to": AGENT_ID}).json()["code"] == "CSRF_FAILED"
    assert client.patch("/api/inquiries/1/status", json={"status": "완료"}).status_code == 403


def test_status_change_by_assigned_agent(client, db, inquiries):
    login(client, "agent1")
    r = patch(client, "/api/inquiries/3/status", {"status": "완료"})
    assert r.status_code == 200 and r.json()["status"] == "완료"
    assert patch(client, "/api/inquiries/3/status", {"status": "완료"}).json()["code"] == "INVALID_STATE"
    assert patch(client, "/api/inquiries/3/status", {"status": "담당자 처리"}).status_code == 200  # 다시 열기
    assert audit_rows(db) == [("status_change", 3, "검토 대기", "완료"), ("status_change", 3, "완료", "담당자 처리")]


def test_agent_cannot_change_other_agents_inquiry(client, db, inquiries):
    """기획서 완료 기준: 상담원이 다른 상담원에게 배정된 문의 수정 → 403"""
    from backend.core.security import hash_password
    from backend.database.models import AdminUser
    from backend.tests.conftest import TEST_PASSWORD as PW
    db.add(AdminUser(username="agent2", role="agent", display_name="상담원2", password_hash=hash_password(PW)))
    db.commit()
    login(client, "agent2")
    assert patch(client, "/api/inquiries/2/status", {"status": "완료"}).status_code == 403   # agent1 담당
    assert patch(client, "/api/inquiries/1/status", {"status": "완료"}).status_code == 403   # 미배정


@pytest.mark.parametrize("value", ["자동 처리", "접수", "아무거나"])
def test_status_only_manual_values(client, inquiries, value):
    login(client, "admin")
    assert patch(client, "/api/inquiries/1/status", {"status": value}).status_code == 422

def test_staff_list_admin_only(client, inquiries):
    login(client, "agent1")
    assert client.get("/api/admin/staff").status_code == 403
    client.cookies.clear()
    login(client, "admin")
    r = client.get("/api/admin/staff")
    assert r.status_code == 200 and [u["username"] for u in r.json()] == ["agent1", "admin"]