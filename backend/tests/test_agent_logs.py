"""AI 실행 로그 API 테스트: 권한(상담원은 배정된 문의만), 필터, 합계, 기간, 페이지."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.database.models import AgentLog, Faq, Inquiry
from backend.tests.conftest import TEST_PASSWORD

KST = timezone(timedelta(hours=9))


def login(client, username):
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200


@pytest.fixture()
def logs(db):
    db.add(Faq(code="F01", category="배송", question="배송은 얼마나 걸리나요?", answer="보통 1~2일 걸립니다."))
    now = datetime.now(KST).replace(hour=12)

    def add(n, decision, tool, *, decided_by="LLM", success=True, confidence=0.95, error=None, days_ago=0,
            assigned=None, latency=4000, faqs=()):
        i = Inquiry(inquiry_number=f"INQ-T-{n:04d}", customer_name="고객", customer_email=f"c{n}@example.com",
                    title=f"문의 {n}", content="c", status="자동 처리", assigned_to=assigned)
        db.add(i)
        db.flush()
        db.add(AgentLog(inquiry_id=i.id, category="배송", confidence=confidence, decision=decision, decided_by=decided_by,
                        selected_tool=tool, tool_success=success, error=error, latency_ms=latency,
                        retrieved_faqs=[[f, 0.8] for f in faqs], used_faq_ids=list(faqs),
                        tokens={"input": 100, "output": 50, "calls": 2} if decided_by == "LLM" else {"calls": 0},
                        created_at=(now - timedelta(days=days_ago)).astimezone(timezone.utc)))

    add(1, "자동 답변", "FAQ 검색", faqs=("F01",))
    add(2, "답변 초안", "배송 조회", success=False, assigned=2)                       # 도구 실패, 상담원1 담당
    add(3, "담당자 연결", "상담원 이관", decided_by="규칙", confidence=0.6, latency=0, assigned=2)
    add(4, "답변 초안", "티켓 접수", error="TimeoutError", latency=20000)
    add(5, "자동 답변", "FAQ 검색", days_ago=10, latency=6000)                        # 기간 필터용
    db.commit()


def test_admin_sees_all_with_summary(client, logs):
    login(client, "admin")
    r = client.get("/api/admin/agent-logs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert [i["inquiry_number"] for i in body["items"]][0] == "INQ-T-0004"      # 최신순 (같은 날은 id 역순)
    s = body["summary"]
    assert s["by_decision"] == {"자동 답변": 2, "답변 초안": 2, "담당자 연결": 1}
    assert s["by_tool"]["배송 조회"] == {"count": 1, "failed": 1}
    assert list(s["by_tool"])[0] == "FAQ 검색"                                  # 도구 순서 고정
    assert (s["errors"], s["tool_failures"], s["low_confidence"]) == (1, 1, 1)
    assert s["avg_latency_ms"] == round((4000 + 4000 + 20000 + 6000) / 4)       # 규칙 판단(0초)은 평균에서 뺌
    assert s["max_latency_ms"] == 20000 and s["tokens"] == {"input": 400, "output": 200, "calls": 8}
    assert body["faq_titles"] == {"F01": "배송은 얼마나 걸리나요?"}


def test_agent_sees_only_assigned(client, logs):
    login(client, "agent1")
    body = client.get("/api/admin/agent-logs").json()
    assert sorted(i["inquiry_number"] for i in body["items"]) == ["INQ-T-0002", "INQ-T-0003"]
    assert body["summary"]["count"] == 2


def test_filters(client, logs):
    login(client, "admin")

    def numbers(**params):
        return sorted(i["inquiry_number"][-1] for i in client.get("/api/admin/agent-logs", params=params).json()["items"])

    assert numbers(decision="답변 초안") == ["2", "4"]
    assert numbers(selected_tool="FAQ 검색") == ["1", "5"]
    assert numbers(tool_success="false") == ["2"]
    assert numbers(decided_by="규칙") == ["3"]
    assert numbers(problem="true") == ["2", "3", "4"]                           # 도구 실패·확신도 낮음·오류
    today = datetime.now(KST).date()
    assert numbers(**{"from": str(today - timedelta(days=6)), "to": str(today)}) == ["1", "2", "3", "4"]
    first = client.get("/api/admin/agent-logs", params={"inquiry_id": 1}).json()
    assert first["total"] == 1 and first["items"][0]["inquiry_id"] == 1


def test_paging_and_validation(client, logs):
    login(client, "admin")
    p2 = client.get("/api/admin/agent-logs", params={"size": 2, "page": 2}).json()
    assert p2["total"] == 5 and len(p2["items"]) == 2 and p2["summary"]["count"] == 5
    assert client.get("/api/admin/agent-logs", params={"decision": "없음"}).status_code == 422
    assert client.get("/api/admin/agent-logs", params={"from": "2026-11-10", "to": "2026-11-01"}).status_code == 422


def test_needs_login(client, logs):
    assert client.get("/api/admin/agent-logs").status_code == 401
