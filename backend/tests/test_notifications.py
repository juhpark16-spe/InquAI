"""알림 API 테스트: 배정·추가 문의·기한 임박·👎 평가가 맞는 사람에게만 가는지, 읽음 처리."""

from datetime import datetime, timedelta, timezone

from backend.database.models import AdminAuditLog, AnalysisResult, CustomerMessage, Inquiry, Response
from backend.services import sla
from backend.tests.conftest import TEST_PASSWORD

ADMIN, AGENT = 1, 2


def login(client, username):
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200


def inquiry(db, n, *, assigned=None, status="담당자 처리", urgency="보통", hours_ago=1.0):
    i = Inquiry(inquiry_number=f"INQ-N-{n:04d}", customer_name=f"고객{n}", customer_email=f"n{n}@example.com",
                title=f"문의 {n}", content="내용", status=status, assigned_to=assigned,
                created_at=sla.sub_weekday_time(datetime.now(timezone.utc), timedelta(hours=hours_ago)))   # 평일 기준 (기한은 주말 제외)
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
    b = inquiry(db, 2, assigned=AGENT, hours_ago=23.5)                   # 기한 30분 남음 (평일 기준)
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
    # 주말에는 답변 기한이 멈춰(월요일 00:00부터 다시 셈) '기한 30분 남음'이 1시간 안이 아님 → 임박 알림 없음
    due = set() if sla.is_weekend(now) else {("due_soon", "INQ-N-0002")}
    assert got == {("assigned", "INQ-N-0001"), ("followup", "INQ-N-0003"), ("bad_rating", "INQ-N-0004")} | due

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


def test_internal_memo_notifies_assignee_not_writer(client, db):
    """내가 맡은 문의에 다른 사람이 남긴 상담원 공유 메모 → 🔔 'memo'. 내가 남긴 메모는 알리지 않음. 목록에 메모 개수"""
    a = inquiry(db, 1, assigned=AGENT)
    db.commit()

    login(client, "admin")
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    assert client.post(f"/api/inquiries/{a.id}/notes", json={"text": "택배사에 분실 조사 요청함. 내일 오전 회신"}).status_code == 201
    assert ("memo", "INQ-N-0001") not in set(kinds(client))                 # 쓴 사람(관리자)에게는 알리지 않음

    client.cookies.clear()
    login(client, "agent1")
    r = client.get("/api/notifications").json()["items"]
    memo = [x for x in r if x["kind"] == "memo"]
    assert len(memo) == 1 and memo[0]["inquiry_number"] == "INQ-N-0001" and "택배사에 분실 조사" in memo[0]["text"]
    assert client.get("/api/inquiries").json()["items"][0]["note_count"] == 1
    note = client.get(f"/api/inquiries/{a.id}").json()["notes"][0]
    assert note["author_id"] == ADMIN and note["author"] == "관리자"          # 화면이 내 메모인지 가려 'New' 배지

    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
    client.post(f"/api/inquiries/{a.id}/notes", json={"text": "고객에게 안내 완료"})   # 내가 남긴 메모
    assert len([x for x in kinds(client) if x[0] == "memo"]) == 1
