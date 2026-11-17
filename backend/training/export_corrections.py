"""상담원이 고친 분류(label_corrections)를 재학습용 CSV로 내보냅니다 (4주차 "수정 데이터로 재학습 시연").

    python -m backend.training.export_corrections                # data/corrections/ 에 저장
    python -m backend.training.export_corrections --since 2026-11-01

결과 (학습 스크립트 train.py 형식: text + 라벨 컬럼)
    data/corrections/category_corrections.csv   text, category, model_label, inquiry_number, corrected_at
    data/corrections/sentiment_corrections.csv   text, sentiment, model_label, inquiry_number, corrected_at

- 한 문의를 여러 번 고쳤으면 **마지막 정답**을 쓰고, model_label은 **처음 모델이 고른 라벨**입니다.
- 고친 뒤 다시 원래대로 돌린 경우(정답 = 모델 라벨)는 모델이 맞았던 것이라 빼지 않고 그대로 둡니다 (확인용).
- 문의 원문에는 고객이 쓴 개인 정보가 있을 수 있어 data/corrections/ 는 GitHub에 올리지 않습니다 (.gitignore).
  학습 데이터에 합치기 전에 docs/labeling_guide.md 기준으로 한 번 더 확인합니다 (docs/db_schema.md).
"""

import argparse
import csv
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "corrections"
KST = timezone(timedelta(hours=9))


def collect(db, since: date | None = None) -> dict[str, list[dict]]:
    """{field: [행, ...]}. 문의·항목마다 한 줄 (마지막 정답, 처음 모델 라벨)"""
    from backend.database.models import Inquiry, LabelCorrection, as_utc

    stmt = select(LabelCorrection, Inquiry.inquiry_number).join(Inquiry, Inquiry.id == LabelCorrection.inquiry_id)
    if since:
        stmt = stmt.where(LabelCorrection.created_at >= datetime.combine(since, time.min, KST).astimezone(timezone.utc))
    latest: dict[tuple[int, str], dict] = {}
    for c, number in db.execute(stmt.order_by(LabelCorrection.id)).all():
        key = (c.inquiry_id, c.field)
        first = latest.get(key, {}).get("model_label", c.before_label)
        latest[key] = {"text": c.text, c.field: c.after_label, "model_label": first, "inquiry_number": number,
                       "corrected_at": as_utc(c.created_at).astimezone(KST).strftime("%Y-%m-%d %H:%M")}
    out: dict[str, list[dict]] = {"category": [], "sentiment": []}
    for (_, field), row in latest.items():
        out[field].append(row)
    return out


def write(rows: dict[str, list[dict]], out_dir: Path = OUT_DIR) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for field, items in rows.items():
        path = out_dir / f"{field}_corrections.csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["text", field, "model_label", "inquiry_number", "corrected_at"])
            w.writeheader()
            w.writerows(items)
        paths[field] = path
    return paths


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="상담원이 고친 분류를 재학습용 CSV로")
    p.add_argument("--since", type=date.fromisoformat, help="이 날짜(KST) 이후에 고친 것만 (YYYY-MM-DD)")
    args = p.parse_args()

    from backend.database.session import SessionLocal

    with SessionLocal() as db:
        rows = collect(db, args.since)
    for field, path in write(rows).items():
        changed = sum(r[field] != r["model_label"] for r in rows[field])
        print(f"[{field}] {len(rows[field])}건 (모델과 다른 정답 {changed}건) → {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
