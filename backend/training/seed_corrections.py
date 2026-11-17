"""재학습 시연용 분류 수정 데이터 만들기: 상담원이 일하면서 고치는 것을 흉내 냅니다.

    python -m backend.training.seed_corrections --dry-run   # 지금 모델이 틀리는 문장만 보여 줌 (DB 안 건드림)
    python -m backend.training.seed_corrections             # 시연 DB에 문의 + 분류 수정으로 넣음
    python -m backend.training.export_corrections           # 재학습용 CSV로 내보내기

1. data/test/written_pool.csv(직접 작성, 정답 유형 포함)의 문장을 **지금 서버의 분류 모델**로 분류합니다 (이 컴퓨터 안에서만).
2. 모델이 틀린 문장만 시연 문의로 만들고, 담당 상담원이 유형을 고친 것으로 남깁니다 (서버의 분류 수정과 같은 코드).
   맞힌 문장은 상담원이 고칠 일이 없으므로 넣지 않습니다.
3. 재학습 효과는 겹치지 않는 문장(data/test/written_eval.csv)으로 잽니다 (docs/retraining.md).

- 문의는 최근 14일 평일 근무 시간에 흩어 넣고, 처리는 '완료'로 둡니다. 이미 같은 문장이 있으면 건너뜀 (여러 번 돌려도 됨).
- 시연 DB를 다시 만들면(seed_demo --reset) 지워지므로, 그 뒤에 다시 돌립니다.
"""

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[2]
POOL = ROOT / "data" / "test" / "written_pool.csv"
KST = timezone(timedelta(hours=9))
SEED = 2026


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="재학습 시연용 분류 수정 데이터")
    p.add_argument("--pool", default=str(POOL))
    p.add_argument("--dry-run", action="store_true", help="틀리는 문장만 보여 주고 DB는 건드리지 않음")
    args = p.parse_args()

    from backend.ai.classifier import Analyzer
    from backend.core.config import get_settings
    from backend.core.security import hash_password
    from backend.database.models import AdminUser, AnalysisResult, Customer, Inquiry, utcnow
    from backend.database.session import SessionLocal
    from backend.services.assignment import pick_assignee
    from backend.services.corrections import apply_correction

    pool = pd.read_csv(args.pool, encoding="utf-8")
    analyzer = Analyzer(get_settings())
    wrong = []
    for row in pool.itertuples():
        a = analyzer.analyze(row.text)
        if a["category"] != row.category:
            wrong.append((row, a))
    print(f"[분류] {len(pool)}문장 중 모델이 틀린 문장 {len(wrong)}개 → 상담원이 고칠 대상")
    for row, a in wrong:
        print(f"  AI {a['category']} ({a['confidence']:.2f}) → 정답 {row.category} | {row.text}")
    if args.dry_run:
        return

    rng = random.Random(SEED)
    now = utcnow()
    with SessionLocal() as db:
        customers = db.scalars(select(Customer).order_by(Customer.id)).all()
        admin = db.scalar(select(AdminUser).where(AdminUser.role == "admin").order_by(AdminUser.id))
        if not customers or admin is None:
            raise SystemExit("시연 DB가 비어 있습니다. 먼저 python -m backend.database.seed_demo --reset")
        password = hash_password("test1234")
        added = 0
        for row, a in wrong:
            if db.scalar(select(Inquiry).where(Inquiry.content == row.text)):
                continue
            day = (now - timedelta(days=rng.randint(1, 13))).astimezone(KST)
            created = day.replace(hour=rng.randint(10, 17), minute=rng.randint(0, 59)).astimezone(timezone.utc)
            customer = rng.choice(customers)
            seq = len(db.scalars(select(Inquiry.id).where(Inquiry.inquiry_number.like(
                f"INQ-{created.astimezone(KST):%Y%m%d}-%"))).all()) + 1
            inquiry = Inquiry(inquiry_number=f"INQ-{created.astimezone(KST):%Y%m%d}-{seq + 50:04d}",
                              customer_name=customer.name, customer_email=customer.email,
                              lookup_password_hash=password, title=row.text[:30], content=row.text,
                              status="완료", privacy_agreed_at=created, created_at=created, updated_at=created)
            db.add(inquiry)
            db.flush()
            db.add(AnalysisResult(inquiry_id=inquiry.id, created_at=created, decision="담당자 연결", decided_by="규칙",
                                  decision_reason="시연용 분류 수정 데이터 (상담원이 처리)",
                                  **{k: a[k] for k in ("category", "confidence", "sentiment", "sentiment_confidence",
                                                       "urgency", "route", "scores", "model_version")}))
            db.flush()
            db.refresh(inquiry)
            agent, _, _ = pick_assignee(db, row.category)   # 정답 유형 담당 상담원이 고친 것으로
            agent = agent or admin
            inquiry.assigned_to = agent.id
            apply_correction(db, inquiry, agent, category=row.category,
                             at=created + timedelta(minutes=rng.randint(20, 180)))
            added += 1
        db.commit()
    print(f"[저장] 시연 문의 + 분류 수정 {added}건 (이미 있던 문장은 건너뜀)")


if __name__ == "__main__":
    main()
