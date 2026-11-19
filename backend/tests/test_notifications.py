"""알림 API 테스트: 배정·추가 문의·기한 임박·👎 평가가 맞는 사람에게만 가는지, 읽음 처리."""

from datetime import datetime, timedelta, timezone

from backend.database.models import AdminAuditLog, AnalysisResult, CustomerMessage, Inquiry, Response
from backend.tests.conftest import TEST_PASSWORD

ADMIN, AGENT = 1, 2


def login(client, username):
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200


def inquiry(db, n, *, assigned=None, status="담당자 처리", urgency="보통", hours_ago=1.0):
    i = Inquiry(inquiry_number=f"INQ-N-{n:04d}", customer_name=f"고객{n}", customer_email=f"n{n}@example.com",
                title=f"문의 {n}", content="내용", status=status, assigned_to=assigned,
                created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago))
    db.add(i)
    db.flush()
    db.add(AnalysisResult(inquiry_id=i.id, category="배송", confidence=0.9, sentiment="중립", sentiment_confidence=0.9,
                          urgency=urgency, route="조회형", decision="담당자 연결", decided_by="규칙",
                          model_version="t", scores={}))
    return i


def kinds(client):
    return [(x["kind"], x["inquiry_number"]) for x in client.get("/api/notifications").json()["items"]]


def test_each_kind_goes_to_the_right_person(client, db):
    now = datetime.now(timezone.utc)
    a = inquiry(db, 1, assigned=AGENT)                                   # 상담원에게 자동 배정
    db.add(AdminAuditLog(admin_id=None, action="auto_assign", target_type="inquiry", target_id=a.id,
                         detail={"assigned_to": AGENT}))
    b = inquiry(db, 2, assigned=AGENT, hours_ago=23.5)                   # 기한 30분 남음
    c = inquiry(db, 3, assigned=AGENT)                                   # 고객 추가 문의
    db.add(CustomerMessage(inquiry_id=c.id, content="추가로 궁금해요"))
    d = inquiry(db, 4, assigned=AGENT, status="완료")                    # 상담원이 보낸 답변에 👎
    db.add(Response(inquiry_id=d.id, draft_text="답", final_text="답", status="발송", approved_by=AGENT,
                    rating=-1, rated_at=now))
    e = inquiry(db, 5, status="자동 처리")                                # AI 자동 답변에 👎 → 관리자만
    db.add(Response(inquiry_id=e.id, draft_text="답", status="발송", rating=-1, rated_at=now))
    inquiry(db, 6, urgency="높음", status="접수")                         # 미배정 긴급 → 관리자만
    inquiry(db, 7, assigned=AGENT, hours_ago=30)                         # 기한 지남 → 임박 알림 아님
    old = inquiry(db, 8, assigned=AGENT)                                 # 8일 전 추가 문의 → 빠짐
    db.add(CustomerMessage(inquiry_id=old.id, content="오래됨", created_at=now - timedelta(days=8)))
    db.commit()

    assert client.get("/api/notifications").status_code == 401

    login(client, "agent1")
    got = set(kinds(client))
    assert got == {("assigned", "INQ-N-0001"), ("due_soon", "INQ-N-0002"), ("followup", "INQ-N-0003"),
                   ("bad_rating", "INQ-N-0004")}

    login(client, "admin")
    got = set(kinds(client))
    assert ("bad_rating", "INQ-N-0004") in got and ("bad_rating", "INQ-N-0005") in got   # 관리자는 모든 👎
    assert ("assigned", "INQ-N-0006") in got                                              # 미배정 긴급
    assert ("assigned", "INQ-N-0001") not in got                                          # 남에게 배정된 건 아님
    assert ("followup", "INQ-N-0003") not in got                                          # 상담원 담당 문의


def test_my_own_assignment_is_not_notified(client, db):
    i = inquiry(db, 1, assigned=ADMIN)
    db.add(AdminAuditLog(admin_id=ADMIN, action="assign", target_type="inquiry", target_id=i.id,
                         detail={"before": {"assigned_to": None}, "after": {"assigned_to": ADMIN}}))
    j = inquiry(db, 2, assigned=AGENT)
    db.add(AdminAuditLog(admin_id=ADMIN, action="assign", target_type="inquiry", target_id=j.id,
                         detail={"before": {"assigned_to": None}, "after": {"assigned_to": AGENT}}))
    db.commit()
    login(client, "admin")
    assert ("assigned", "INQ-N-0001") not in kinds(client)
    login(client, "agent1")
    assert ("assigned", "INQ-N-0002") in kinds(client)       # 관리자가 상담원에게 배정 → 상담원 알림


def test_seen_clears_unread_and_new_ones_count_again(client, db):
    c = inquiry(db, 1, assigned=AGENT)
    db.add(CustomerMessage(inquiry_id=c.id, content="추가 문의"))
    db.commit()
    login(client, "agent1")
    r = client.get("/api/notifications").json()
    assert r["unread"] == 1 and r["items"][0]["unread"] is True

    assert client.post("/api/notifications/seen").status_code == 403          # CSRF 헤더 없으면 거부
    assert client.post("/api/notifications/seen", headers={"X-CSRF-Token": client.cookies.get("csrf_token")}).status_code == 200
    r = client.get("/api/notifications").json()
    assert r["unread"] == 0 and r["items"][0]["unread"] is False

    db.add(CustomerMessage(inquiry_id=c.id, content="또 추가 문의",
                           created_at=datetime.now(timezone.utc) + timedelta(seconds=1)))
    db.commit()
    assert client.get("/api/notifications").json()["unread"] == 1
