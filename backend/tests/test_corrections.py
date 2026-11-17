"""분류 수정 (PATCH /api/inquiries/{id}/analysis) → label_corrections (재학습 데이터), 규칙 재계산, 내보내기"""

import pytest
from sqlalchemy import select

from backend.database.models import AdminAuditLog, AnalysisResult, Inquiry, LabelCorrection
from backend.tests.conftest import TEST_PASSWORD
from backend.training.export_corrections import collect, write

TEXT = "환불이 아직 안 들어왔어요. 빨리 처리해 주세요."


@pytest.fixture()
def inquiry(db):
    i = Inquiry(inquiry_number="INQ-C-1", customer_name="고객", customer_email="c@example.com", title="환불",
                content=TEXT, status="담당자 처리", assigned_to=2)
    other = Inquiry(inquiry_number="INQ-C-2", customer_name="남", customer_email="x@example.com", title="t",
                    content="다른 문의", status="담당자 처리", assigned_to=None)
    bare = Inquiry(inquiry_number="INQ-C-3", customer_name="분석 없음", customer_email="y@example.com", title="t",
                   content="분석 실패한 문의", status="검토 대기", assigned_to=2)
    db.add_all([i, other, bare])
    db.flush()
    for x in (i, other):  # 모델이 '배송·중립'으로 잘못 분류
        db.add(AnalysisResult(inquiry_id=x.id, category="배송", confidence=0.71, sentiment="중립", sentiment_confidence=0.8,
                              urgency="낮음", route="조회형", decision="담당자 연결", decided_by="규칙",
                              model_version="t", scores={}))
    db.commit()
    return {"id": i.id, "other": other.id, "bare": bare.id}


def login(client, username="agent1"):
    client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_correct_category_and_sentiment(client, db, inquiry):
    h = login(client)
    due_before = client.get(f"/api/inquiries/{inquiry['id']}").json()["due_at"]
    r = client.patch(f"/api/inquiries/{inquiry['id']}/analysis", headers=h,
                     json={"category": "반품·환불", "sentiment": "부정"})
    assert r.status_code == 200
    a = r.json()
    # 규칙 재계산: 반품·환불 → 접수형, 돈 관련 유형 + 부정 → 긴급도 높음
    assert (a["category"], a["sentiment"], a["route"], a["urgency"]) == ("반품·환불", "부정", "접수형", "높음")
    assert a["confidence"] == 0.71                                # 모델 확신도는 그대로 (모델이 낸 값)

    rows = db.scalars(select(LabelCorrection).where(LabelCorrection.inquiry_id == inquiry["id"])
                      .order_by(LabelCorrection.id)).all()
    assert [(c.field, c.before_label, c.after_label) for c in rows] == [("category", "배송", "반품·환불"),
                                                                       ("sentiment", "중립", "부정")]
    assert all(c.text == TEXT and c.corrected_by == 2 for c in rows)  # 원문 복사본 (재학습 CSV용)

    detail = client.get(f"/api/inquiries/{inquiry['id']}").json()
    assert detail["due_at"] < due_before                          # 긴급(4시간)이 되어 답변 기한이 당겨짐
    assert len(detail["corrections"]) == 2
    last = detail["history"][-1]
    assert last["kind"] == "correct" and last["actor"] == "상담원1"
    assert last["text"] == "분류 수정: 유형 배송 → 반품·환불 · 감정 중립 → 부정 · 처리 경로 조회형 → 접수형 · 긴급도 낮음 → 높음"
    audit = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "label_correct"))
    assert audit.detail["changes"] == {"category": ["배송", "반품·환불"], "sentiment": ["중립", "부정"]}


def test_invalid_requests(client, db, inquiry):
    h = login(client)
    url = f"/api/inquiries/{inquiry['id']}/analysis"
    assert client.patch(url, headers=h, json={}).status_code == 422                       # 아무것도 안 고름
    assert client.patch(url, headers=h, json={"category": "불만"}).status_code == 422       # 없는 유형
    r = client.patch(url, headers=h, json={"category": "배송"})
    assert r.status_code == 400 and r.json()["code"] == "NO_CHANGE"
    r = client.patch(f"/api/inquiries/{inquiry['bare']}/analysis", headers=h, json={"category": "배송"})
    assert r.status_code == 400 and r.json()["code"] == "NO_ANALYSIS"
    assert client.patch(f"/api/inquiries/{inquiry['other']}/analysis", headers=h,
                        json={"category": "교환"}).status_code in (403, 404)               # 배정 안 된 문의
    assert db.scalar(select(LabelCorrection)) is None


def test_export_uses_last_answer_and_first_model_label(client, db, inquiry, tmp_path):
    h = login(client)
    url = f"/api/inquiries/{inquiry['id']}/analysis"
    client.patch(url, headers=h, json={"category": "결제"})
    client.patch(url, headers=h, json={"category": "반품·환불"})   # 다시 고침
    rows = collect(db)
    assert rows["sentiment"] == []
    assert len(rows["category"]) == 1
    row = rows["category"][0]
    assert (row["text"], row["category"], row["model_label"], row["inquiry_number"]) == (TEXT, "반품·환불", "배송", "INQ-C-1")
    path = write(rows, tmp_path)["category"]
    assert path.read_text(encoding="utf-8-sig").splitlines()[0] == "text,category,model_label,inquiry_number,corrected_at"


def test_dashboard_counts_corrections(client, db, inquiry):
    h = login(client)
    client.patch(f"/api/inquiries/{inquiry['id']}/analysis", headers=h, json={"category": "반품·환불", "sentiment": "부정"})
    login(client, "admin")
    c = client.get("/api/stats/summary").json()["ai"]["corrections"]
    assert (c["category"], c["sentiment"], c["by_category"]) == (1, 1, {"배송": 1})
