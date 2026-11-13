"""긴급도 규칙과 처리 경로 매핑 (기획서 2-2 기준).

모델이 예측한 유형·감정과 문의 원문을 받아 긴급도와 기본 처리 경로를 정합니다.
확신도가 낮거나 강한 불만이면 이관형으로 바꾸는 판단은 에이전트(LangGraph)가 합니다.
"""

# 처리 경로 4갈래
ROUTE_LOOKUP = "조회형"      # 배송 조회 도구
ROUTE_TICKET = "접수형"      # 티켓 접수 도구 (티켓 종류만 다르게 저장)
ROUTE_FAQ = "FAQ형"          # FAQ 검색 후 답변
ROUTE_ESCALATE = "이관형"    # 상담원 배정

CATEGORY_TO_ROUTE = {
    "배송": ROUTE_LOOKUP,
    "주문 취소": ROUTE_TICKET,
    "교환": ROUTE_TICKET,
    "반품·환불": ROUTE_TICKET,
    "결제": ROUTE_FAQ,
    "상품": ROUTE_FAQ,
    "쿠폰·적립금·회원": ROUTE_FAQ,
    "기타": ROUTE_ESCALATE,
}

# 감정이 부정이면 긴급도 "높음"이 되는 돈 관련 유형
MONEY_CATEGORIES = {"반품·환불", "결제"}

# 이런 표현이 있으면 유형·감정과 관계없이 긴급도 "높음" (띄어쓰기는 무시하고 비교)
#   재촉·반복: 당장, 아직도, 몇 번째
#   돈 문제: 고객 돈이 실제로 나간 문의는 담담하게 써도 급함
#            ("결제 오류 났는데 돈은 빠져나갔어요"는 감정 모델이 중립으로 봐서 높음을 놓쳤음)
#            '빠져나갔'만 쓰면 "박스에서 빠져나갔는지", "빠져나갔던 돈이 다시 들어오잖아요?"까지 걸려서
#            돈·금액 + 빠져나갔, 실제로 일어난 두 번 결제(됐/되었/되던)만 넣음
#            ("두 번 결제하면 가능한가요?"는 앞으로의 계획이라 제외)
URGENT_EXPRESSIONS = [
    "당장", "아직도", "벌써몇번째", "몇번째",
    "돈이빠져나갔", "돈은빠져나갔", "돈만빠져나갔", "돈빠져나갔", "금액이빠져나갔", "금액은빠져나갔",
    "두번결제됐", "두번결제되었", "두번결제되던", "두번결제가됐", "이중결제",
]


def get_route(category: str) -> str:
    """유형의 기본 처리 경로. 정의되지 않은 유형은 상담원 이관."""
    return CATEGORY_TO_ROUTE.get(category, ROUTE_ESCALATE)


def has_urgent_expression(text: str) -> bool:
    compact = "".join(text.split())
    return any(expr in compact for expr in URGENT_EXPRESSIONS)


def get_urgency(category: str, sentiment: str, text: str) -> str:
    """긴급도: 높음 / 보통 / 낮음."""
    if sentiment == "부정" and category in MONEY_CATEGORIES:
        return "높음"
    if has_urgent_expression(text):
        return "높음"

    route = get_route(category)
    if route in (ROUTE_LOOKUP, ROUTE_FAQ):
        return "낮음"
    # 접수형, 그리고 기획서에 따로 정하지 않은 이관형(기타)은 보통
    return "보통"
