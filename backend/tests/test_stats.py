"""대시보드 통계 API 테스트: 날짜별(KST) 집계, 처리·미처리, 긴급 미처리, AI 지표, 권한."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.api.stats import KST
from backend.database.models import AgentLog, AnalysisResult, Inquiry, Response
from backend.services import sla
from backend.tests.conftest import TEST_PASSWORD


def add(db, n, status, category, urgency, decision, *, days_ago=0, hour=12, assigned=None, confidence=0.95,
        decided_by="LLM", latency=8000, error=None):
    created = (datetime.now(KST) - timedelta(days=days_ago)).replace(hour=hour, minute=0, second=0, microsecond=0)
    i = Inquiry(inquiry_number=f"INQ-T-{n:04d}", customer_name="고객", customer_email=f"c{n}@example.com",
                title="t", content="c", status=status, assigned_to=assigned,
                created_at=created.astimezone(timezone.utc))
    db.add(i)
    db.flush()
    db.add(AnalysisResult(inquiry_id=i.id, category=category, confidence=confidence, sentiment="중립",
                          sentiment_confidence=0.9, urgency=urgency, route="FAQ형", decision=decision,
                          decided_by=decided_by, model_version="t", scores={}))
    db.add(AgentLog(inquiry_id=i.id, category=category, confidence=confidence, decision=decision,
                    decided_by=decided_by, latency_ms=latency, error=error,
                    tokens={"input": 100, "output": 50, "calls": 2} if decided_by == "LLM" else {"calls": 0}))
    return i


@pytest.fixture()
def data(db):
    add(db, 1, "자동 처리", "배송", "낮음", "자동 답변")
    add(db, 2, "자동 처리", "배송", "낮음", "자동 답변", latency=6000)
    add(db, 3, "담당자 처리", "결제", "높음", "담당자 연결", decided_by="규칙", latency=0, assigned=2)
    add(db, 4, "검토 대기", "교환", "보통", "답변 초안", error="TimeoutError")
    add(db, 5, "완료", "반품·환불", "높음", "담당자 연결", days_ago=2, decided_by="규칙", latency=0, confidence=0.6)
    add(db, 6, "담당자 처리", "기타", "보통", "담당자 연결", days_ago=10, decided_by="규칙", latency=0)  # 기간 밖
    # KST 자정 직후(=UTC 전날 15시대) 문의는 KST 날짜로 묶여야 함
    add(db, 7, "접수", "상품", "낮음", "답변 초안", hour=0, decided_by="규칙", latency=0)
    i = add(db, 8, "완료", "상품", "낮음", "답변 초안", days_ago=1)
    db.add(Response(inquiry_id=i.id, draft_text="초안", final_text="초안", status="발송", approved_by=1,
                    is_edited=False))
    db.commit()


def login(client, username="admin"):
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200


def test_admin_only(client, data):
    assert client.get("/api/stats/summary").status_code == 401
    login(client, "agent1")
    assert client.get("/api/stats/summary").status_code == 403


def test_summary(client, data):
    login(client)
    s = client.get("/api/stats/summary").json()
    assert s["range"]["days"] == 7 and len(s["daily"]) == 7
    assert s["kpi"]["total"] == 7                     # 10일 전 문의는 빠짐
    assert s["kpi"]["today"] == 5                     # 오늘: 1,2,3,4,7 (7은 KST 0시)
    assert s["kpi"]["auto_rate"] == round(2 / 7, 4)
    assert s["kpi"]["approval_without_edit_rate"] == 1.0

    today = s["daily"][-1]
    assert today["date"] == datetime.now(KST).date().isoformat()
    assert (today["total"], today["open"], today["done"]) == (5, 3, 2)
    assert today["by_category"]["배송"] == 2 and today["by_category"]["상품"] == 1
    assert list(today["by_category"]) == ["배송", "주문 취소", "교환", "반품·환불", "결제", "상품",
                                          "쿠폰·적립금·회원", "기타"]  # 유형 순서 고정 (그래프 색 순서)

    assert s["by_status"]["자동 처리"] == 2 and s["by_urgency"]["높음"] == 2
    assert s["by_decision"] == {"자동 답변": 2, "답변 초안": 3, "담당자 연결": 2}
    assert s["by_decided_by"] == {"규칙": 3, "LLM": 4}
    assert s["ai"]["avg_latency_ms"] == round((8000 + 6000 + 8000 + 8000) / 4)
    assert s["ai"]["low_confidence"] == 1 and s["ai"]["errors"] == 1 and s["ai"]["draft_failures"] == 0


def test_now_counts_ignore_range(client, data):
    """미처리 현황은 기간과 관계없이 지금 쌓여 있는 일 (10일 전 미처리 문의도 포함)"""
    login(client)
    now = client.get("/api/stats/summary", params={"from": "2020-01-01", "to": "2020-01-02"}).json()["now"]
    overdue = now.pop("overdue_open")
    assert now == {"open": 4, "urgent_open": 1, "review_waiting": 1, "unassigned_open": 3}
    assert overdue >= 1  # 10일 전 미처리(#6)는 24시간 기한을 넘김 (#3은 테스트 시각에 따라 달라 범위로 확인)


def test_staff_counts(client, data):
    login(client)
    staff = {s["display_name"]: s for s in client.get("/api/stats/summary").json()["staff"]}
    assert (staff["상담원1"]["open"], staff["상담원1"]["urgent_open"]) == (1, 1)


@pytest.mark.parametrize("params", [{"from": "2026-11-10", "to": "2026-11-01"}, {"from": "2026-01-01", "to": "2026-12-31"}])
def test_invalid_range(client, data, params):
    login(client)
    assert client.get("/api/stats/summary", params=params).status_code == 422


def test_list_open_filter(client, data):
    login(client)
    r = client.get("/api/inquiries", params={"open": "true", "urgency": "높음"})
    assert [i["inquiry_number"] for i in r.json()["items"]] == ["INQ-T-0003"]


def test_previous_period_and_daily_auto(client, data):
    """지난 기간(같은 일수) 값으로 증감을 계산할 수 있어야 함. 10일 전 문의는 바로 앞 7일에 들어감"""
    login(client)
    s = client.get("/api/stats/summary").json()
    p = s["previous"]
    today = datetime.now(KST).date()
    assert p["to"] == (today - timedelta(days=7)).isoformat()
    assert p["from"] == (today - timedelta(days=13)).isoformat()
    assert p["total"] == 1 and p["auto_rate"] == 0.0 and p["avg_latency_ms"] is None  # 규칙 판단 1건
    assert s["daily"][-1]["auto"] == 2
    assert sum(d["auto"] for d in s["daily"]) == 2


def test_activity(client, data):
    assert client.get("/api/stats/activity").status_code == 401
    login(client, "agent1")
    assert client.get("/api/stats/activity").status_code == 403
    login(client)
    items = client.get("/api/stats/activity?limit=5").json()
    assert 0 < len(items) <= 5
    times = [e["at"] for e in items]
    assert times == sorted(times, reverse=True)  # 최신순
    e = items[0]
    assert {"at", "actor", "text", "kind", "inquiry_id", "inquiry_number", "title"} <= set(e)


def test_draft_failures_are_counted_apart_from_errors(client, db):
    add(db, 51, "검토 대기", "상품", "보통", "답변 초안", error="초안 작성 실패 APITimeoutError")
    add(db, 52, "검토 대기", "배송", "보통", "답변 초안", error="TimeoutError: 에이전트 처리 시간 초과")
    db.commit()
    login(client)
    ai = client.get("/api/stats/summary").json()["ai"]
    assert (ai["errors"], ai["draft_failures"]) == (1, 1)


def test_products(client, db):
    """상품별 문의: 옵션이 달라도 같은 상품으로 묶고, 가장 많은 유형으로 상세페이지 개선 힌트"""
    from backend.database.models import Customer, Order

    cust = Customer(name="고객", email="p@example.com", phone="010")
    db.add(cust)
    db.flush()
    now = datetime.now(timezone.utc)
    for number, name in [("O-1", "와이드 데님 팬츠 (연청, 28)"), ("O-2", "와이드 데님 팬츠 (진청, 30)"), ("O-3", "선크림")]:
        db.add(Order(customer_id=cust.id, order_number=number, product_name=name, amount=1, order_status="배송 완료",
                     ordered_at=now))
    for n, (number, cat, decision) in enumerate([("O-1", "교환", "답변 초안"), ("O-2", "교환", "답변 초안"),
                                                 ("O-1", "상품", "자동 답변"), ("O-3", "배송", "자동 답변"),
                                                 ("없는주문", "배송", "자동 답변"), (None, "결제", "자동 답변")], start=1):
        i = add(db, 100 + n, "자동 처리", cat, "낮음", decision)
        i.order_number = number
    db.commit()
    login(client)
    body = client.get("/api/stats/products").json()
    assert (body["total"], body["linked"], body["products"]) == (6, 4, 2)          # 실제 주문에 연결된 문의만
    top = body["items"][0]
    assert top["product"] == "와이드 데님 팬츠" and top["count"] == 3
    assert top["by_category"] == {"교환": 2, "상품": 1} and top["top_category"] == "교환"
    assert "사이즈표" in top["hint"] and top["auto"] == 1 and len(top["examples"]) == 3
    assert client.get("/api/stats/products", params={"limit": 1}).json()["items"][0]["product"] == "와이드 데님 팬츠"
    one = body["items"][1]
    assert one["product"] == "선크림" and one["top_category"] is None and one["hint"] is None   # 1건뿐이면 신호 아님


def test_products_admin_only(client, db):
    login(client, "agent1")
    assert client.get("/api/stats/products").status_code == 403


def test_priorities(client, db):
    """대시보드 '지금 할 일': 가장 급한 문의(긴급도 → 오래된 순)와 기한이 남은 문의(기한 가까운 순)"""
    now = datetime.now(timezone.utc)

    def at(i, hours_ago):
        i.created_at = sla.sub_weekday_time(now, timedelta(hours=hours_ago))   # 평일 기준 (기한은 주말 제외)

    at(add(db, 1, "담당자 처리", "결제", "높음", "담당자 연결"), 1)    # 긴급, 기한 3시간 남음
    at(add(db, 2, "검토 대기", "배송", "보통", "답변 초안"), 23)      # 기한 1시간 남음
    at(add(db, 3, "접수", "상품", "낮음", "답변 초안"), 30)           # 기한 지남 → 임박 목록에서 빠짐
    at(add(db, 4, "담당자 처리", "교환", "높음", "담당자 연결"), 5)    # 긴급이고 더 오래됨 → 가장 급한 문의 (기한은 지남)
    at(add(db, 5, "완료", "배송", "높음", "담당자 연결"), 10)          # 처리 끝 → 빠짐
    db.commit()

    assert client.get("/api/stats/priorities").status_code == 401
    login(client, "agent1")
    assert client.get("/api/stats/priorities").status_code == 403

    login(client)
    r = client.get("/api/stats/priorities").json()
    assert r["open"] == 4
    assert r["next"]["inquiry_number"] == "INQ-T-0004" and r["next"]["overdue"] is True
    assert [x["inquiry_number"] for x in r["due_soon"]] == ["INQ-T-0002", "INQ-T-0001"]
    assert r["due_soon"][0]["preview"] == "c"
