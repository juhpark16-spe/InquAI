"""쇼핑몰 정책 값 한곳에 (docs/shop_policy.md 와 같아야 함). 정책이 바뀌면 여기만 고칩니다.

쓰는 곳: 주문 정보 카드(inquiry_context), 바로 처리(order_actions), 티켓 승인(api/tickets), 주문·배송 조회(api/customers)
문의 상태(미처리 등)는 답변 기한과 함께 services/sla.py OPEN_STATUSES.
"""

CANCELLABLE = ("결제 완료", "상품 준비 중")    # 출고 전: 취소·배송지·옵션 변경 가능 (2장)
SHIPPING = ("출고", "배송 중")                 # 출고 뒤 배송 완료 전
RETURN_DAYS, DEFECT_RETURN_DAYS = 7, 30        # 반품·교환 기한: 단순 변심 / 불량·오배송 (4장)
RETURN_FEE = 6000                              # 단순 변심 반품·교환 왕복 배송비 (F17·F19)
FREE_SHIPPING_MIN, SHIPPING_FEE = 30000, 3000  # 3만원 이상 무료배송, 아니면 3,000원 (F15·F28)
REFUND_BUSINESS_DAYS = 3                       # 반품 검수 뒤 환불까지 영업일 (F18)
DELAY_DAYS = 4                                 # 주문 후 이만큼 지나도 배송 완료가 아니면 '배송 지연' (평일 출고 + 1~2일, 주말 여유)


def refund_timing(method: str | None) -> str:
    """결제 수단별 환불(승인 취소) 반영 기간 (F29, 화면 frontend/.../inquiry-detail/Tickets.tsx refundTiming 과 같은 기준)"""
    if method == "무통장입금":
        return "고객 환불 계좌로 1~2영업일 (환불 계좌를 먼저 받아야 함)"
    if method in ("계좌이체", "간편결제"):
        return f"{method} 1~3영업일 안에 반영"
    return f"{method or '카드'} 3~5영업일 안에 반영 (카드사 사정)"


def partial_refund(amount: int, qty: int, count: int) -> tuple[int, int, int]:
    """출고 전 부분 취소: (환불액, 뺀 배송비, 남는 금액). 무료배송(3만원 이상) 주문이 3만원 미만이 되면 처음 배송비 3,000원을 빼고 환불 (F28).
    바로 처리(order_actions)와 문의하기의 환불 미리 보기(refund_preview)가 같은 계산을 씀"""
    unit = amount // qty
    left = amount - unit * count
    fee = SHIPPING_FEE if amount >= FREE_SHIPPING_MIN > left else 0
    return unit * count - fee, fee, left
