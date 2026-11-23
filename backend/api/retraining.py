"""재학습 현황 API (관리자, 4주차): 상담원이 고친 분류가 얼마나 쌓였는지, 모델이 자주 틀리는 패턴, 모델 버전별 점수.

    GET /api/admin/retraining

- 분류 수정(label_corrections)은 상담원이 문의 상세에서 [분류 고치기]로 남긴 것입니다 (services/corrections.py).
- "새 수정"은 지금 모델을 학습한 뒤에 쌓인 수정 = 다음 재학습에 쓸 데이터입니다.
- 모델 버전·점수는 evaluation/model_history.json 에서 읽습니다 (docs/model_card.md 와 같은 값).
- 재학습 자체는 GPU가 필요하고 15분쯤 걸려 화면 버튼 대신 명령으로 합니다 (docs/retraining.md).
- recommend: 새 수정 50건 이상 또는 같은 패턴의 새 수정 10건 이상이면 '재학습 권장'과 이유.
"""

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from fastapi import APIRouter

from backend.core.config import get_settings
from backend.core.dependencies import DB, AdminOnly
from backend.database.models import LabelCorrection, as_utc

router = APIRouter(prefix="/admin", tags=["재학습 현황"])
HISTORY = Path(__file__).resolve().parents[2] / "evaluation" / "model_history.json"
FIELD_LABEL = {"category": "유형", "sentiment": "감정"}
# 재학습 권장 기준: 새 수정이 이만큼 쌓였거나, 같은 패턴(예: 배송 → 교환)의 새 수정이 이만큼 반복되면
RECOMMEND_PENDING = 50
RECOMMEND_PATTERN = 10


def recommendation(pending: int, patterns: list[dict]) -> dict:
    """재학습을 권장할지와 이유 (관리자가 숫자를 보고 따로 판단하지 않아도 되게)"""
    reasons = []
    if pending >= RECOMMEND_PENDING:
        reasons.append(f"새 분류 수정이 {pending}건 쌓였어요 (기준 {RECOMMEND_PENDING}건)")
    reasons += [f"'{p['before']} → {p['after']}' 수정이 새로 {p['pending']}건 반복됐어요 (기준 {RECOMMEND_PATTERN}건)"
                for p in patterns if p["pending"] >= RECOMMEND_PATTERN]
    return {"needed": bool(reasons), "reasons": reasons, "pending_threshold": RECOMMEND_PENDING,
            "pattern_threshold": RECOMMEND_PATTERN}


def load_history(path: Path = HISTORY) -> list[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))["versions"]
    except (OSError, ValueError, KeyError):
        return []


@router.get("/retraining", summary="재학습 현황 (관리자)")
def retraining_status(_: AdminOnly, db: DB):
    history = load_history(HISTORY)
    version = get_settings().category_model_version
    current = next((v for v in history if v.get("current")), None) or {"version": version}
    trained_at = datetime.fromisoformat(current["trained_at"]) if current.get("trained_at") else None

    rows = db.scalars(select(LabelCorrection).options(selectinload(LabelCorrection.inquiry))
                      .order_by(LabelCorrection.created_at.desc(), LabelCorrection.id.desc())).all()
    pending = lambda c: trained_at is None or as_utc(c.created_at) > trained_at  # noqa: E731

    patterns: dict[tuple, dict] = defaultdict(lambda: {"count": 0, "pending": 0, "examples": []})
    for c in rows:
        p = patterns[(c.field, c.before_label, c.after_label)]
        p["count"] += 1
        p["pending"] += pending(c)
        if len(p["examples"]) < 3:
            p["examples"].append({"inquiry_id": c.inquiry_id, "text": c.text[:120]})

    pattern_list = sorted(({"field": FIELD_LABEL.get(f, f), "before": b, "after": a, **v}
                           for (f, b, a), v in patterns.items()), key=lambda x: -x["count"])
    pending_total = sum(pending(c) for c in rows)
    return {
        "model": {**current, "version": version},
        "recommend": recommendation(pending_total, pattern_list),
        "corrections": {
            "total": len(rows),
            "by_field": {FIELD_LABEL.get(f, f): sum(c.field == f for c in rows) for f in ("category", "sentiment")},
            "pending": pending_total,   # 지금 모델 학습 뒤에 쌓인 수정 (다음 재학습 대상)
        },
        "patterns": pattern_list,
        "recent": [{"id": c.id, "inquiry_id": c.inquiry_id,
                    "inquiry_number": c.inquiry.inquiry_number if c.inquiry else None,
                    "field": FIELD_LABEL.get(c.field, c.field), "before": c.before_label, "after": c.after_label,
                    "text": c.text[:200], "at": as_utc(c.created_at).isoformat(), "pending": pending(c)}
                   for c in rows[:20]],
        "history": history,
    }
