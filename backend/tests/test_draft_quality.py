"""AI 초안 수정 분석 테스트: 비교 계산(그대로/조금/많이, 고친 방식, AI 글 비율), API 집계·예시·권한, 시연 데이터."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.database.models import AdminAuditLog, AnalysisResult, Inquiry, Response
from backend.services.draft_quality import compare, segments
from backend.tests.conftest import TEST_PASSWORD
from backend.tests.test_seed_demo import last_tuesday_11am, seeded

DRAFT = "출고 전이라 배송지를 바꾸실 수 있습니다. 마이페이지에서 새 주소를 입력해 주세요."


def test_compare_levels_and_kinds():
    same = compare(DRAFT, DRAFT + "  ")                       # 앞뒤 공백만 다르면 그대로
    assert same == {"change": 0.0, "level": "그대로", "kind": None, "ai_share": 1.0, "added": 0, "removed": 0}

    added = compare(DRAFT, DRAFT + " 감사합니다.")
    assert added["level"] == "조금 고침" and added["kind"] == "덧붙임" and added["removed"] == 0
    assert 0.8 < added["ai_share"] < 1

    cut = compare(DRAFT, "출고 전이라 배송지를 바꾸실 수 있습니다.")
    assert cut["kind"] == "줄임" and cut["added"] == 0 and cut["ai_share"] == 1.0

    rewrite = compare(DRAFT, "이미 출고되어 배송지를 바꿀 수 없습니다. 택배사 고객센터로 요청해 주세요.")
    assert rewrite["level"] == "많이 고침" and rewrite["kind"] == "고쳐 씀" and rewrite["change"] >= 0.2


def test_segments_by_words():
    segs = segments("배송비 3,000원이 차감됩니다.", "배송비는 차감되지 않습니다.")
    assert "".join(s["text"] for s in segs if s["op"] != "add") == "배송비 3,000원이 차감됩니다."
    assert "".join(s["text"] for s in segs if s["op"] != "del") == "배송비는 차감되지 않습니다."
    assert {s["op"] for s in segs} == {"del", "add", "same"}
    assert segments("같은 글", "같은 글") == [{"op": "same", "text": "같은 글"}]


def add(db, n, category, draft, final, *, approved_by=2, days_ago=1, generated_by="llm", status="발송"):
    sent = datetime.now(timezone.utc) - timedelta(days=days_ago)
    i = Inquiry(inquiry_number=f"INQ-D-{n:04d}", customer_name="고객", customer_email=f"d{n}@example.com",
                title=f"문의 {n}", content="c", status="완료")
    db.add(i)
    db.flush()
    db.add(AnalysisResult(inquiry_id=i.id, category=category, confidence=0.9, sentiment="중립", sentiment_confidence=0.9,
                          urgency="보통", route="FAQ형", model_version="t", scores={}))
    db.add(Response(inquiry_id=i.id, draft_text=draft, final_text=final, generated_by=generated_by, status=status,
                    approved_by=approved_by, approved_at=sent if status == "발송" else None,
                    created_at=sent - timedelta(minutes=10)))
    return i


@pytest.fixture()
def data(db):
    add(db, 1, "배송", DRAFT, DRAFT)
    add(db, 2, "배송", DRAFT, DRAFT)
    add(db, 3, "배송", DRAFT, DRAFT + " 감사합니다.")
    add(db, 4, "교환", DRAFT, "이미 출고되어 배송지를 바꿀 수 없습니다. 택배사 고객센터로 요청해 주세요.", approved_by=1)
    add(db, 5, "배송", DRAFT, DRAFT, approved_by=None)              # 자동 발송: 상담원 검토가 아님
    add(db, 6, "배송", DRAFT, DRAFT, generated_by="agent_user")    # 상담원이 직접 씀: 비교할 초안 없음
    add(db, 7, "배송", DRAFT, DRAFT, days_ago=40)                  # 기간 밖
    add(db, 8, "배송", DRAFT, None, approved_by=None, status="초안")  # 검토를 기다리는 초안
    db.add(AdminAuditLog(admin_id=2, action="draft_generate", target_type="inquiry", target_id=1,
                         detail={"instruction": "더 짧게"}))
    db.add(AdminAuditLog(admin_id=2, action="draft_generate", target_type="inquiry", target_id=2, detail={}))
    db.commit()


def login(client, username="admin"):
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200


def test_drafts_summary(client, data):
    login(client)
    body = client.get("/api/stats/drafts").json()
    s = body["summary"]
    assert (s["count"], s["unedited"], s["unedited_rate"]) == (4, 2, 0.5)
    assert s["levels"] == {"그대로": 2, "조금 고침": 1, "많이 고침": 1}
    assert s["kinds"] == {"덧붙임": 1, "줄임": 0, "고쳐 씀": 1}
    assert s["waiting"] == 1 and s["median_wait_min"] == 10.0 and 0 < s["ai_share"] < 1
    assert [(g["category"], g["count"], g["unedited"]) for g in body["by_category"]] == [("배송", 3, 2), ("교환", 1, 0)]
    assert {g["id"]: g["count"] for g in body["by_staff"]} == {2: 3, 1: 1}
    assert len(body["daily"]) == 30 and sum(d["count"] for d in body["daily"]) == 4
    assert body["regenerate"] == {"count": 2, "with_instruction": 1, "top_instructions": [{"text": "더 짧게", "count": 1}]}
    ex = body["examples"]
    assert [e["inquiry_number"] for e in ex] == ["INQ-D-0004", "INQ-D-0003"]       # 많이 고친 순
    assert ex[0]["level"] == "많이 고침" and ex[0]["segments"][0]["op"] in ("del", "add")


def test_drafts_range_and_auth(client, data):
    assert client.get("/api/stats/drafts").status_code == 401
    login(client, "agent1")
    assert client.get("/api/stats/drafts").status_code == 403
    login(client)
    assert client.get("/api/stats/drafts", params={"from": "2026-11-10", "to": "2026-11-01"}).status_code == 422
    assert client.get("/api/stats/drafts", params={"examples": 0}).json()["examples"] == []


def test_demo_data_has_edited_drafts(client, db):
    seeded(db, now=last_tuesday_11am())   # 실행한 요일·시각에 따라 보낸 초안 수가 바뀌지 않게 고정
    login(client)
    s = client.get("/api/stats/drafts").json()["summary"]
    assert s["count"] >= 5 and 0 < s["levels"]["그대로"] < s["count"]   # 그대로 보낸 것과 고친 것이 섞임 (시연 데이터는 날짜와 상관없이 7~11건)
    assert s["levels"]["많이 고침"] > 0
    sent = db.query(Response).filter(Response.generated_by == "llm", Response.approved_by.isnot(None)).all()
    assert all(r.is_edited == (r.final_text != r.draft_text) for r in sent)
