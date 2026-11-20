"""상담원이 문의 상세에서 바로 처리하는 일 (조건 검사 + 처리 + 기록).

| 처리 | 조건 | 결과 |
| --- | --- | --- |
| address 배송지 변경 | 출고 전 | 주문 배송지 변경 |
| option 옵션 변경 | 출고 전 + 같은 상품의 다른 옵션, 품절 아님 | 상품명의 옵션(괄호) 변경, 가격 같음 |
| partial_cancel 부분 취소 | 출고 전 + 수량 2개 이상, 남기는 수량 1개 이상 | 수량·금액 줄임 + 결제 내역 '승인 취소'(부분) + 열린 취소 티켓은 승인 처리 |
| duplicate_cancel 중복 승인 취소 | 중복 결제 의심 (같은 금액 승인 10분 안에 두 번) | 결제 내역 '승인 취소' 1건 |
| points 보상 적립금 | 쇼핑몰 고객 + 한도 (상담원 3,000원, 관리자 50,000원) | 적립금 내역 +금액 |
| coupon 사과 쿠폰 | 쇼핑몰 고객 + 쿠폰 종류별 권한 | 쿠폰 발급 (30일) |
| return 반품 회수 접수 | 배송 완료 + 기한 안 (단순 변심 7일, 불량·오배송 30일) + 아직 접수 전 | 반품 접수 시각, 회수 예정 안내 |

주문 처리는 **문의에 적힌 주문이고 문의 이메일과 주문자 이메일이 같을 때만** 합니다 (본인 확인).
모든 처리는 작업 기록(order_action)에 바뀌기 전·후와 함께 남고, 문의 처리 이력·AI 초안의 처리 기록에 들어갑니다.
"""

import re
from datetime import timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.errors import AppError
from backend.database.models import (AdminUser, Coupon, Customer, Inquiry, Order, Payment, PointHistory, Ticket,
                                     as_utc, utcnow)
from backend.services.audit import add_audit

CANCELLABLE = ("결제 완료", "상품 준비 중")       # 출고 전 (docs/shop_policy.md 2장)
RETURN_DAYS, DEFECT_RETURN_DAYS = 7, 30
POINT_LIMIT = {"agent": 3000, "admin": 50000}     # 1회 보상 적립금 한도
DUPLICATE_WINDOW = timedelta(minutes=10)

# 상품별 옵션 (상품명 괄호 안). 품절 옵션은 바꿀 수 없음
PRODUCT_OPTIONS: dict[str, list[str]] = {
    "오버핏 코튼 맨투맨": ["그레이, M", "그레이, L", "그레이, XL", "블랙, M", "블랙, L", "네이비, L"],
    "와이드 데님 팬츠": ["연청, 26", "연청, 28", "연청, 30", "진청, 28", "진청, 30"],
    "경량 패딩 조끼": ["블랙, S", "블랙, M", "블랙, L", "카키, M"],
    "니트 가디건": ["아이보리, FREE", "베이지, FREE", "차콜, FREE"],
    "러닝화 에어 쿠션": ["화이트, 250", "화이트, 260", "화이트, 270", "블랙, 260"],
    "가죽 크로스백": ["브라운", "블랙"],
    "극세사 이불 세트": ["퀸", "킹", "슈퍼싱글"],
    "유아 내복 세트": ["90", "100", "110"],
}
SOLD_OUT = {("와이드 데님 팬츠", "진청, 30"), ("니트 가디건", "차콜, FREE"), ("러닝화 에어 쿠션", "화이트, 270")}

# 사과 쿠폰: 이름 → (혜택, 최소 주문 금액, 상담원도 발급 가능)
COUPONS = {
    "사과 쿠폰 3,000원": ("3,000원 할인", 20000, True),
    "무료배송 쿠폰": ("배송비 무료", 0, True),
    "사과 쿠폰 5,000원": ("5,000원 할인", 30000, False),
}


def split_product(name: str) -> tuple[str, str | None]:
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", name)
    return (m.group(1), m.group(2)) if m else (name, None)


def option_choices(order: Order) -> list[dict]:
    base, current = split_product(order.product_name)
    return [{"option": o, "sold_out": (base, o) in SOLD_OUT, "current": o == current}
            for o in PRODUCT_OPTIONS.get(base, [])]


def duplicates(order: Order) -> list[Payment]:
    """아직 정리되지 않은 중복 승인: 같은 금액 승인이 10분 안에 두 번 → 뒤 승인. 같은 금액의 '승인 취소'가 있으면 정리된 것으로
    (주문 전체가 취소된 주문은 원래 승인 1건 몫의 취소를 빼고 셈. 부분 취소처럼 금액이 다른 취소는 세지 않음)"""
    approvals = [p for p in order.payments if p.kind == "승인"]
    dup = [b for a, b in zip(approvals, approvals[1:])
           if a.amount == b.amount and as_utc(b.at) - as_utc(a.at) <= DUPLICATE_WINDOW]
    left = []
    for d in dup:
        cancels = sum(1 for p in order.payments if p.kind == "승인 취소" and p.amount == d.amount)
        if order.order_status == "취소":
            cancels -= 1
        if cancels < len([x for x in dup if x.amount == d.amount]):
            left.append(d)
    return left[-1:] if left else []


def won(n: int) -> str:
    return f"{n:,}원"


def _order(db: Session, inquiry: Inquiry) -> Order:
    if not inquiry.order_number:
        raise AppError(409, "문의에 주문번호가 없어 처리할 수 없습니다. 고객에게 주문번호를 먼저 받아 주세요.", "NO_ORDER")
    row = db.execute(select(Order, Customer).join(Customer).where(Order.order_number == inquiry.order_number)).first()
    if row is None:
        raise AppError(404, "주문을 찾을 수 없습니다.", "NOT_FOUND")
    order, customer = row
    if customer.email.lower() != inquiry.customer_email.lower():
        raise AppError(409, "문의 이메일과 주문자 이메일이 달라 처리할 수 없습니다. 본인 확인 후 진행해 주세요.", "NOT_OWNER")
    return order


def _customer(db: Session, inquiry: Inquiry) -> Customer:
    c = db.scalar(select(Customer).where(func.lower(Customer.email) == inquiry.customer_email.lower()))
    if c is None:
        raise AppError(404, "쇼핑몰 고객 정보가 없어 적립금·쿠폰을 줄 수 없습니다 (비회원).", "NOT_MEMBER")
    return c


def _before_shipping(order: Order) -> None:
    if order.order_status not in CANCELLABLE:
        raise AppError(409, f"이미 '{order.order_status}' 상태라 바꿀 수 없습니다 (출고 전에만 가능).", "INVALID_STATE")


def run(db: Session, request: Request, user: AdminUser, inquiry: Inquiry, action: str, body: dict) -> str:
    """처리하고 기록을 남긴 뒤, 화면에 보여 줄 결과 문장을 돌려줌 (커밋은 부르는 쪽에서)"""
    now = utcnow()
    before: dict = {}
    after: dict = {}
    order: Order | None = None

    if action == "address":
        order = _order(db, inquiry)
        _before_shipping(order)
        address = (body.get("address") or "").strip()
        if len(address) < 5:
            raise AppError(422, "새 배송지를 정확히 적어 주세요.", "VALIDATION_ERROR")
        before, after = {"address": order.shipping_address}, {"address": address}
        order.shipping_address = address
        summary = f"배송지 변경: {address}"

    elif action == "option":
        order = _order(db, inquiry)
        _before_shipping(order)
        base, current = split_product(order.product_name)
        new = (body.get("option") or "").strip()
        if new not in PRODUCT_OPTIONS.get(base, []):
            raise AppError(422, "이 상품에 없는 옵션입니다.", "VALIDATION_ERROR")
        if new == current:
            raise AppError(422, "지금과 같은 옵션입니다.", "VALIDATION_ERROR")
        if (base, new) in SOLD_OUT:
            raise AppError(409, f"'{new}'은(는) 품절이라 바꿀 수 없습니다.", "SOLD_OUT")
        before, after = {"option": current}, {"option": new}
        order.product_name = f"{base} ({new})"
        summary = f"옵션 변경: {current} → {new}"

    elif action == "partial_cancel":
        order = _order(db, inquiry)
        _before_shipping(order)
        count = int(body.get("count") or 0)
        qty = order.quantity or 1
        if not 1 <= count < qty:
            raise AppError(422, f"1개부터 {qty - 1}개까지 취소할 수 있습니다 (전부 취소는 취소 티켓 승인으로).", "VALIDATION_ERROR")
        unit = order.amount // qty
        before, after = {"quantity": qty, "amount": order.amount}, {"quantity": qty - count, "amount": order.amount - unit * count}
        order.quantity, order.amount = qty - count, order.amount - unit * count
        db.add(Payment(order_id=order.id, kind="승인 취소", method=order.payment_method, amount=unit * count, at=now,
                       memo=f"부분 취소 {count}개"))
        for t in db.scalars(select(Ticket).where(Ticket.inquiry_id == inquiry.id, Ticket.ticket_type == "취소",
                                                 Ticket.status == "접수")):
            t.status, t.memo, t.handled_by, t.handled_at = "승인", f"부분 취소 {count}개로 처리", user.id, now
        summary = f"부분 취소: {qty}개 → {qty - count}개 ({won(unit * count)} 승인 취소)"

    elif action == "duplicate_cancel":
        order = _order(db, inquiry)
        left = duplicates(order)
        if not left:
            raise AppError(409, "정리되지 않은 중복 승인이 없습니다.", "INVALID_STATE")
        target = left[0]
        db.add(Payment(order_id=order.id, kind="승인 취소", method=target.method, amount=target.amount, at=now,
                       memo=f"중복 승인 1건 취소 (승인번호 {target.approval_no})"))
        after = {"approval_no": target.approval_no, "amount": target.amount}
        summary = f"중복 승인 1건 취소: {won(target.amount)} (승인번호 {target.approval_no}, 카드사에 따라 3~5영업일 안에 반영)"

    elif action == "points":
        customer = _customer(db, inquiry)
        amount = int(body.get("amount") or 0)
        limit = POINT_LIMIT.get(user.role, 0)
        if not 100 <= amount <= limit:
            raise AppError(403 if amount > limit else 422,
                           f"보상 적립금은 100원~{won(limit)}까지 줄 수 있습니다" + (" (더 큰 금액은 관리자에게)." if user.role != "admin" else "."),
                           "LIMIT_EXCEEDED" if amount > limit else "VALIDATION_ERROR")
        reason = (body.get("reason") or "").strip()[:50] or "상담 보상"
        db.add(PointHistory(customer_id=customer.id, amount=amount, reason=f"상담 보상: {reason}", at=now,
                            expires_at=now + timedelta(days=365)))
        after = {"amount": amount, "reason": reason}
        summary = f"보상 적립금 {won(amount)} 지급 ({reason})"

    elif action == "coupon":
        customer = _customer(db, inquiry)
        name = body.get("coupon")
        if name not in COUPONS:
            raise AppError(422, "없는 쿠폰입니다.", "VALIDATION_ERROR")
        benefit, min_amount, agent_ok = COUPONS[name]
        if not agent_ok and user.role != "admin":
            raise AppError(403, f"'{name}'은(는) 관리자만 발급할 수 있습니다.", "LIMIT_EXCEEDED")
        db.add(Coupon(customer_id=customer.id, name=name, benefit=benefit, min_amount=min_amount,
                      expires_at=now + timedelta(days=30)))
        after = {"coupon": name}
        summary = f"쿠폰 발급: {name} ({benefit}, 30일)"

    elif action == "return":
        order = _order(db, inquiry)
        if order.order_status != "배송 완료" or not order.delivered_at:
            raise AppError(409, "배송 완료된 주문만 반품 회수를 접수할 수 있습니다.", "INVALID_STATE")
        if order.return_requested_at:
            raise AppError(409, "이미 반품이 접수된 주문입니다.", "INVALID_STATE")
        reason = body.get("reason") if body.get("reason") in ("단순 변심", "불량·오배송") else "단순 변심"
        days = DEFECT_RETURN_DAYS if reason == "불량·오배송" else RETURN_DAYS
        if now > as_utc(order.delivered_at) + timedelta(days=days):
            raise AppError(409, f"{reason} 반품 기한({days}일)이 지났습니다.", "INVALID_STATE")
        order.return_requested_at = now
        after = {"reason": reason}
        fee = "왕복 배송비 6,000원은 환불 금액에서 차감" if reason == "단순 변심" else "배송비는 쇼핑몰 부담"
        summary = f"반품 회수 접수 ({reason}): 1~3영업일 안에 택배 기사 방문, {fee}"

    else:
        raise AppError(422, "알 수 없는 처리입니다.", "VALIDATION_ERROR")

    add_audit(db, request, "order_action", user, "inquiry", inquiry.id, kind=action, summary=summary,
              order_number=order.order_number if order else None, before=before, after=after)
    return summary
