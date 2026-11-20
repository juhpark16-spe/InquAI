"""모의 주문·고객의 상담용 상세 데이터: 결제·승인 내역, 수량, 택배사·배송 추적 단계, 적립금 내역, 쿠폰.

seed_data.seed_orders 가 주문을 만든 뒤 부릅니다. 기존 주문·고객 배정이 바뀌지 않도록 **따로 정한 난수 시드**를 씁니다
(시연 시나리오가 특정 고객의 '결제 완료' 주문을 쓰기 때문, docs/demo_scenario.md).
시연 문의에 맞춘 특별한 내역(중복 승인, 환불 지연·차감, 적립금 소멸 등)은 seed_demo.py 가 문의를 만들 때 덧붙입니다.
"""

import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.database.models import Coupon, Customer, Order, Payment, PointHistory, ShipmentEvent, as_utc

DETAIL_SEED = 2026
METHODS = [("신용카드", 55), ("간편결제", 25), ("계좌이체", 12), ("무통장입금", 8)]
CARRIERS = ["CJ대한통운", "롯데택배", "한진택배", "우체국택배"]
POINT_RATE = 0.01          # 구매 금액의 1% 적립 (구매 확정 후, docs/shop_policy.md)
POINT_VALID_DAYS = 365


def approval_no(rng: random.Random) -> str:
    return f"{rng.randint(10_000_000, 99_999_999)}"


def _events(order: Order, rng: random.Random, now: datetime) -> list[tuple[datetime, str, str | None]]:
    """주문 상태에 맞는 배송 추적 단계 (출고 → 간선 → 지역 HUB → 배송 출발 → 배송 완료)"""
    ordered = as_utc(order.ordered_at)
    end = as_utc(order.delivered_at) or now
    span = max((end - ordered).total_seconds(), 3600 * 6)
    at = lambda f: ordered + timedelta(seconds=span * f)  # noqa: E731
    steps = [(at(0.35), "택배사 인수", "이천 물류센터")]
    if order.order_status in ("배송 중", "배송 완료"):
        steps += [(at(0.5), "간선 상차", "곤지암 HUB"), (at(0.65), "간선 하차", rng.choice(["대전 HUB", "옥천 HUB", "청원 HUB"]))]
        if order.order_status == "배송 완료" or "배송 출발" in (order.shipping_status or ""):
            steps.append((at(0.85), "배송 출발", "담당 기사 배정"))
    if order.order_status == "배송 완료":
        steps.append((end, "배송 완료", (order.shipping_status or "").removeprefix("배송 완료").strip(" ()") or "문 앞"))
    return [s for s in steps if s[0] <= now]


def seed_order_details(db: Session, customers: list[Customer], orders: list[Order], now: datetime) -> None:
    rng = random.Random(DETAIL_SEED)
    for o in orders:
        if o.order_status != "취소" and rng.random() < 0.2:      # 다섯 건 중 한 건은 2개 이상
            o.quantity = 2 if rng.random() < 0.8 else 3
            o.amount *= o.quantity
        o.payment_method = rng.choices([m for m, _ in METHODS], weights=[w for _, w in METHODS])[0]
        delay = timedelta(hours=rng.randint(1, 8)) if o.payment_method == "무통장입금" else timedelta(minutes=rng.randint(0, 3))
        o.paid_at = as_utc(o.ordered_at) + delay
        db.add(Payment(order_id=o.id, kind="승인", method=o.payment_method, amount=o.amount,
                       approval_no=approval_no(rng), at=o.paid_at))
        if o.order_status == "취소":
            db.add(Payment(order_id=o.id, kind="승인 취소", method=o.payment_method, amount=o.amount,
                           at=o.paid_at + timedelta(hours=rng.randint(2, 20)), memo="주문 취소 (출고 전)"))
        if o.tracking_number:
            o.carrier = rng.choice(CARRIERS)
            for at, status, location in _events(o, rng, now):
                db.add(ShipmentEvent(order_id=o.id, at=at, status=status, location=location))

    by_customer: dict[int, list[Order]] = {}
    for o in orders:
        by_customer.setdefault(o.customer_id, []).append(o)
    for c in customers:
        joined = now - timedelta(days=rng.randint(200, 500))
        db.add(PointHistory(customer_id=c.id, amount=3000, reason="신규 가입 적립", at=joined,
                            expires_at=joined + timedelta(days=POINT_VALID_DAYS)))
        for o in by_customer.get(c.id, []):
            if o.order_status == "배송 완료" and as_utc(o.delivered_at) < now - timedelta(days=7):   # 구매 확정된 주문
                at = as_utc(o.delivered_at) + timedelta(days=7)
                db.add(PointHistory(customer_id=c.id, amount=int(o.amount * POINT_RATE), reason="구매 적립",
                                    at=at, expires_at=at + timedelta(days=POINT_VALID_DAYS), order_number=o.order_number))
        if rng.random() < 0.5:
            at = now - timedelta(days=rng.randint(3, 40))
            db.add(PointHistory(customer_id=c.id, amount=500, reason="리뷰 작성 적립", at=at,
                                expires_at=at + timedelta(days=POINT_VALID_DAYS)))
        if rng.random() < 0.4:
            db.add(PointHistory(customer_id=c.id, amount=-2000, reason="주문 결제에 사용",
                                at=now - timedelta(days=rng.randint(10, 60))))

        db.add(Coupon(customer_id=c.id, name="신규 가입 10% 할인", benefit="10% 할인 (최대 1만원)", min_amount=30000,
                      expires_at=joined + timedelta(days=30), used_at=joined + timedelta(days=rng.randint(1, 20))))
        db.add(Coupon(customer_id=c.id, name="무료배송 쿠폰", benefit="배송비 무료", min_amount=0,
                      expires_at=now + timedelta(days=rng.randint(3, 25))))
        if rng.random() < 0.6:
            db.add(Coupon(customer_id=c.id, name="겨울 시즌 5,000원 할인", benefit="5,000원 할인", min_amount=50000,
                          expires_at=now + timedelta(days=rng.randint(5, 40))))
    db.flush()
