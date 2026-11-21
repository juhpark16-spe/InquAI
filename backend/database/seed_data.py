"""모의 고객·주문과 FAQ 넣기 (docs/db_schema.md 4장).

- FAQ: data/faq/faqs.csv 를 code 기준으로 넣거나 고칩니다 (여러 번 실행해도 됨).
- 고객 20명·주문 50건: 날짜를 실행 시각 기준으로 만들어, 언제 시연해도 취소(출고 전)·반품(배송 완료 7일 이내)
  가능 여부가 골고루 나오게 합니다. 결제·승인 내역, 수량, 택배사·배송 추적, 적립금·쿠폰도 함께 (seed_details.py), 상품 옵션·재고 (services/inventory.py). 이미 있으면 건너뛰고, --reset 이면 지우고 다시 만듭니다.

실행 (프로젝트 루트에서)
    python -m backend.database.seed_data
    python -m backend.database.seed_data --reset
"""

import argparse
import random
import sys
from collections import Counter
from datetime import timedelta

import pandas as pd
from sqlalchemy import delete, func, select, update

from backend.core.config import PROJECT_ROOT
from backend.database.models import (Coupon, Customer, Faq, Order, Payment, PointHistory, ShipmentEvent, Ticket,
                                     utcnow)
from backend.database.seed_details import seed_order_details
from backend.database.session import SessionLocal, init_db
from backend.services import inventory

FAQ_FILE = PROJECT_ROOT / "data" / "faq" / "faqs.csv"

NAMES = ["김민준", "이서연", "박지호", "최수아", "정예준", "강하은", "조도윤", "윤지우", "장시우", "임서윤",
         "한주원", "오하린", "서건우", "신지민", "권유준", "황채원", "안현우", "송다은", "전승민", "홍소율"]

# (상품명, 가격)
PRODUCTS = [
    ("오버핏 코튼 맨투맨 (그레이, L)", 39000), ("와이드 데님 팬츠 (연청, 28)", 49000),
    ("경량 패딩 조끼 (블랙, M)", 59000), ("니트 가디건 (아이보리, FREE)", 45000),
    ("러닝화 에어 쿠션 (화이트, 260)", 89000), ("가죽 크로스백 (브라운)", 79000),
    ("무선 블루투스 이어폰 (화이트)", 69000), ("스테인리스 텀블러 500ml (실버)", 25000),
    ("극세사 이불 세트 (퀸)", 99000), ("세라믹 프라이팬 28cm", 42000),
    ("비타민C 세럼 30ml", 32000), ("저자극 선크림 SPF50+", 21000),
    ("유아 내복 세트 (100)", 28000), ("캠핑 접이식 의자 (카키)", 55000),
]

HUBS = ["옥천 HUB 출발", "대전 HUB 도착", "곤지암 HUB 출발", "배송 출발 (담당 기사 배정)"]

# (주문 상태, 건수, 주문 후 경과 일수 범위, 배송 완료 후 경과 일수 범위)
PLAN = [
    ("결제 완료", 6, (0, 1), None),
    ("상품 준비 중", 8, (0, 2), None),
    ("출고", 5, (1, 3), None),
    ("배송 중", 10, (1, 4), None),
    ("배송 완료", 10, (3, 9), (0, 6)),     # 반품·교환 가능 (배송 완료 후 7일 이내)
    ("배송 완료", 8, (12, 30), (8, 25)),   # 반품·교환 기간 지남
    ("취소", 3, (1, 10), None),
]


def seed_faqs(db) -> None:
    df = pd.read_csv(FAQ_FILE, encoding="utf-8-sig")
    added = changed = 0
    for row in df.itertuples():
        faq = db.scalar(select(Faq).where(Faq.code == row.id))
        if faq is None:
            db.add(Faq(code=row.id, category=row.category, question=row.question, answer=row.answer))
            added += 1
        elif (faq.category, faq.question, faq.answer) != (row.category, row.question, row.answer):
            faq.category, faq.question, faq.answer = row.category, row.question, row.answer
            changed += 1
    print(f"[FAQ] {len(df)}개 중 추가 {added}, 수정 {changed}")


def seed_orders(db, reset: bool) -> None:
    if db.scalar(select(func.count()).select_from(Customer)):
        if not reset:
            print("[고객·주문] 이미 있어 건너뜀 (다시 만들려면 --reset)")
            inventory.ensure_catalog(db)
            return
        db.execute(update(Ticket).values(order_id=None))
        for table in (Payment, ShipmentEvent, PointHistory, Coupon):
            db.execute(delete(table))
        db.execute(delete(Order))
        db.execute(delete(Customer))
        print("[고객·주문] 기존 데이터 삭제")

    rng = random.Random(42)
    customers = [Customer(name=n, email=f"customer{i:02d}@example.com",
                          phone=f"010-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}")
                 for i, n in enumerate(NAMES, start=1)]
    db.add_all(customers)
    db.flush()

    now = utcnow()
    per_day = Counter()
    orders = []
    for k, (status, count, (d0, d1), delivered) in enumerate(PLAN):
        for j in range(count):
            # 고객 20명에게 2~3건씩 돌아가며 배정 (한 고객이 여러 상태의 주문을 갖게)
            customer = customers[(k + j * len(PLAN)) % len(customers)]
            ordered_at = now - timedelta(days=rng.randint(d0, d1), hours=rng.randint(0, 23))
            day = ordered_at.strftime("%Y%m%d")
            per_day[day] += 1
            product, price = rng.choice(PRODUCTS)
            shipped = status in ("출고", "배송 중", "배송 완료")
            delivered_at = None
            if delivered:
                delivered_at = now - timedelta(days=rng.randint(*delivered), hours=rng.randint(0, 23))
                delivered_at = max(delivered_at, ordered_at + timedelta(days=1))
            shipping = {"결제 완료": "결제 완료", "상품 준비 중": "상품 준비 중", "출고": "택배사 인수",
                        "배송 중": rng.choice(HUBS), "배송 완료": "배송 완료 (문 앞)", "취소": None}[status]
            orders.append(Order(
                customer_id=customer.id, order_number=f"{day}-{per_day[day]:04d}", product_name=product,
                amount=price, order_status=status, shipping_status=shipping,
                tracking_number=f"{rng.randint(10**11, 10**12 - 1)}" if shipped else None,
                ordered_at=ordered_at, delivered_at=delivered_at,
            ))
    db.add_all(orders)
    db.flush()
    seed_order_details(db, customers, orders, now)   # 결제·승인, 수량, 택배사·배송 추적, 적립금, 쿠폰 (seed_details.py)
    options = inventory.ensure_catalog(db, reset=True)   # 상품 옵션·재고도 처음 재고로 (services/inventory.py)
    print(f"[고객·주문] 고객 {len(customers)}명, 주문 {len(orders)}건 "
          f"({', '.join(f'{s} {c}' for s, c in Counter(o.order_status for o in orders).items())}), 상품 옵션 {options}개")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="모의 고객·주문과 FAQ 넣기")
    p.add_argument("--reset", action="store_true", help="모의 고객·주문을 지우고 다시 만듦")
    args = p.parse_args()

    init_db()
    with SessionLocal() as db:
        seed_faqs(db)
        seed_orders(db, args.reset)
        db.commit()


if __name__ == "__main__":
    main()
