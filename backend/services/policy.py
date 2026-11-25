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
