"""서비스의 표기 재확인 기록(analysis_results.scores.page_recheck)을 재학습용 CSV로 내보냅니다 (증류 2단계, 2026-11-27).

    python -m backend.training.export_page_recheck
    python -m backend.training.export_page_recheck --since 2026-12-01

정답 정하기 (위에서부터)
    1. 상담원이 유형을 고쳤으면 그 정답 (사람)
    2. 아니면 LLM 재확인 답 (선생님). LLM이 실패했거나, 경계 밖이라 서버가 무시한 답은 뺌

결과 (train.py --extra-train 형식)
    data/corrections/page_recheck.csv   text, category, source, model_label, llm_label, inquiry_number

- 합성 문장(distill_page.py)과 달리 **실제 문의 분포**라서 기타 쪽 쏠림이 덜할 것으로 기대합니다.
- 문의 원문에 고객 개인 정보가 있을 수 있어 data/corrections/ 는 GitHub에 올리지 않습니다 (.gitignore).
- 몇십 건으로는 학습 효과가 작습니다. 수백 건이 쌓이면 docs/retraining.md 채택 규칙(seed 3개, 외부 테스트 유지)으로 비교하세요.
"""

import argparse
import csv
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "corrections" / "page_recheck.csv"
KST = timezone(timedelta(hours=9))
FIELDS = ["text", "category", "source", "model_label", "llm_label", "inquiry_number"]


def collect(db, since: date | None = None) -> list[dict]:
    from backend.database.models import AnalysisResult, Inquiry, LabelCorrection

    stmt = select(AnalysisResult, Inquiry).join(Inquiry, Inquiry.id == AnalysisResult.inquiry_id)
    if since:
        stmt = stmt.where(Inquiry.created_at >= datetime.combine(since, time.min, KST).astimezone(timezone.utc))
    human = {}   # 문의 → 상담원의 마지막 유형 정답
    for c in db.scalars(select(LabelCorrection).where(LabelCorrection.field == "category").order_by(LabelCorrection.id)):
        human[c.inquiry_id] = c.after_label
    rows = []
    for a, inquiry in db.execute(stmt.order_by(Inquiry.id)).all():
        rec = (a.scores or {}).get("page_recheck")
        if not rec:
            continue
        if inquiry.id in human:
            category, source = human[inquiry.id], "상담원"
        elif rec.get("llm") and not rec.get("ignored"):
            category, source = rec["llm"], "LLM"
        else:
            continue
        rows.append({"text": inquiry.content, "category": category, "source": source, "model_label": rec["model"],
                     "llm_label": rec.get("llm") or "", "inquiry_number": inquiry.inquiry_number})
    return rows


def write(rows: list[dict], path: Path = OUT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return path


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="표기 재확인 기록을 재학습용 CSV로")
    p.add_argument("--since", type=date.fromisoformat, help="이 날짜(KST) 이후 문의만 (YYYY-MM-DD)")
    args = p.parse_args()

    from backend.database.session import SessionLocal

    with SessionLocal() as db:
        rows = collect(db, args.since)
    path = write(rows)
    by = {s: sum(r["source"] == s for r in rows) for s in ("상담원", "LLM")}
    differ = sum(r["category"] != r["model_label"] for r in rows)
    print(f"{len(rows)}건 (상담원 {by['상담원']} · LLM {by['LLM']}, 분류 모델과 다른 정답 {differ}건) → {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
