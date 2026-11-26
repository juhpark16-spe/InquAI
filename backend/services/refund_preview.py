"""문의하기의 환불 미리 보기 (회원이 주문을 고르고 취소·반품 이야기를 쓸 때, 2026-11-26).

'반품비 동의' 체크 대신 이 주문을 취소·반품하면 얼마가 돌아오는지를 미리 보여 줌 (동의를 받지 않음):
- 출고 전: 전체 취소는 전액, 수량이 2개 이상이면 부분 취소 금액 (무료배송이 깨지면 배송비 3,000원 차감, policy.partial_refund)
- 출고 뒤·배송 완료: 단순 변심 반품은 왕복 배송비 6,000원을 뺀 금액(7일 안), 불량·오배송은 전액(30일 안)
- 결제 수단별 환불 반영 기간
실제 금액은 상담원이 주문·검수 결과로 확정 (화면에 '예정'으로 표시). 비회원은 주문을 알 수 없어 화면이 정책 한 줄만 보여 줌.
"""

from datetime import timedelta

from backend.database.models import Order, as_utc, utcnow
from backend.services.policy import (CANCELLABLE, DEFECT_RETURN_DAYS, RETURN_DAYS, RETURN_FEE, SHIPPING, partial_refund,
                                     refund_timing)

MAX_PARTIAL_ROWS = 5   # 부분 취소 미리 보기는 5개까지만 (수량이 많은 주문에서 줄이 길어지지 않게)


def preview(order: Order) -> dict:
    qty = order.quantity or 1
    out = {"order_number": order.order_number, "product_name": order.product_name, "amount": order.amount,
           "order_status": order.order_status, "refund_timing": refund_timing(order.payment_method),
           "kind": None, "partial": [], "change_refund": None, "defect_refund": None,
           "change_until": None, "defect_until": None}
    if order.order_status in CANCELLABLE:
        out["kind"] = "cancel"
        out["partial"] = [dict(zip(("refund", "fee", "left"), partial_refund(order.amount, qty, n)), count=n)
                          for n in range(1, min(qty, MAX_PARTIAL_ROWS + 1))]
        return out
    if order.order_status in SHIPPING or order.order_status == "배송 완료":
        out["kind"] = "return"
        delivered = as_utc(order.delivered_at)
        now = utcnow()
        change_until = delivered + timedelta(days=RETURN_DAYS) if delivered else None
        defect_until = delivered + timedelta(days=DEFECT_RETURN_DAYS) if delivered else None
        # 아직 배송 중이면 받은 뒤부터 기한이 시작되니 금액만 보여 줌
        if change_until is None or now <= change_until:
            out["change_refund"] = max(order.amount - RETURN_FEE, 0)
        if defect_until is None or now <= defect_until:
            out["defect_refund"] = order.amount
        out["change_until"], out["defect_until"] = change_until, defect_until
    return out
