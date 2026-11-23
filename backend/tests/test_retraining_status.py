"""재학습 현황 API 테스트: 수정 합계, 지금 모델 뒤에 쌓인 새 수정, 자주 틀리는 패턴, 모델 기록, 권한."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.api import retraining
from backend.database.models import Inquiry, LabelCorrection
from backend.tests.conftest import TEST_PASSWORD

TRAINED = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)


@pytest.fixture()
def data(db, tmp_path, monkeypatch):
    history = tmp_path / "model_history.json"
    history.write_text(json.dumps({"versions": [
        {"version": "old", "current": False, "scores": {"external": 0.98}},
        {"version": "category_aug_s42", "current": True, "trained_at": TRAINED.isoformat(), "corrections_used": 2,
         "scores": {"external": 0.981, "written_eval": 0.95}}]}), encoding="utf-8")
    monkeypatch.setattr(retraining, "HISTORY", history)
    i = Inquiry(inquiry_number="INQ-R-0001", customer_name="고객", customer_email="c@example.com", title="t", content="c")
    db.add(i)
    db.flush()
    rows = [("category", "상품", "배송", -2), ("category", "상품", "배송", 1), ("category", "기타", "주문 취소", 2),
            ("sentiment", "중립", "부정", -1)]          # 마지막 숫자: 학습 시각 기준 며칠 뒤 (음수 = 학습 전)
    for f, b, a, days in rows:
        db.add(LabelCorrection(inquiry_id=i.id, field=f, before_label=b, after_label=a, text=f"{b}→{a} 문장",
                               corrected_by=1, created_at=TRAINED + timedelta(days=days)))
    db.commit()


def login(client, username="admin"):
    assert client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD}).status_code == 200


def test_status(client, data):
    login(client)
    body = client.get("/api/admin/retraining").json()
    assert body["model"]["version"] == "category_aug_s42" and body["model"]["corrections_used"] == 2
    assert body["corrections"] == {"total": 4, "by_field": {"유형": 3, "감정": 1}, "pending": 2}
    top = body["patterns"][0]
    assert (top["field"], top["before"], top["after"], top["count"], top["pending"]) == ("유형", "상품", "배송", 2, 1)
    assert body["recent"][0]["before"] == "기타" and body["recent"][0]["pending"] is True     # 최신순
    assert body["recent"][0]["inquiry_number"] == "INQ-R-0001"
    assert [v["version"] for v in body["history"]] == ["old", "category_aug_s42"]


def test_admin_only(client, data):
    assert client.get("/api/admin/retraining").status_code == 401
    login(client, "agent1")
    assert client.get("/api/admin/retraining").status_code == 403


def test_real_history_file_is_valid():
    versions = retraining.load_history(retraining.HISTORY)
    assert sum(v["current"] for v in versions) == 1
    assert all({"version", "scores", "note"} <= set(v) for v in versions)


def test_recommendation_thresholds():
    """재학습 권장: 새 수정 50건 이상 또는 같은 패턴의 새 수정 10건 이상"""
    few = [{"before": "배송", "after": "교환", "pending": 3}]
    assert retraining.recommendation(10, few) == {"needed": False, "reasons": [], "pending_threshold": 50, "pattern_threshold": 10}
    r = retraining.recommendation(12, [{"before": "배송", "after": "교환", "pending": 10}])
    assert r["needed"] and r["reasons"] == ["'배송 → 교환' 수정이 새로 10건 반복됐어요 (기준 10건)"]
    assert retraining.recommendation(50, few)["reasons"][0].startswith("새 분류 수정이 50건")
