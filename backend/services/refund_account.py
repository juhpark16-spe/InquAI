"""환불 계좌: 무통장입금 주문을 취소·반품할 때 돈을 돌려받을 계좌 (정책 F29: 환불 계좌로 1~2영업일).

- 고객은 문의하기·추가 문의의 '환불 계좌' 칸(은행 / 예금주 / 계좌번호)으로 보냄. 문의 글에 계좌번호를 적지 않게 안내.
- 문의 글과 따로 저장(inquiries.refund_*)하고 **AI 분석·초안에는 넘기지 않음** (문의 글은 OpenAI로 보내지기 때문).
  AI 초안 입력에는 '받음 / 아직 없음'만 들어감.
- 고객 화면에는 가려서(국민은행 ****9012 · 홍*동), 상담원 화면도 가려서 보이고 [번호 보기]를 누를 때만 전체 번호 →
  그때마다 작업 기록(refund_account_view)에 남김.
- 시연 프로젝트라 암호화는 하지 않음 (실제 서비스라면 저장할 때 암호화하고 환불이 끝나면 지움).
"""

from sqlalchemy.orm import Session

from backend.database.models import Inquiry, utcnow
from backend.services.inquiry_context import order_card

BANKS = ("국민은행", "신한은행", "우리은행", "하나은행", "농협은행", "기업은행", "SC제일은행", "카카오뱅크", "토스뱅크", "케이뱅크",
         "새마을금고", "우체국", "수협은행", "부산은행", "대구은행", "광주은행", "경남은행", "전북은행", "씨티은행")
NEEDS_CATEGORIES = ("주문 취소", "반품·환불")


def save(inquiry: Inquiry, bank: str, holder: str, number: str) -> None:
    inquiry.refund_bank, inquiry.refund_holder = bank, holder.strip()
    inquiry.refund_account = "".join(ch for ch in number if ch.isdigit())   # 숫자만 저장
    inquiry.refund_account_at = utcnow()


def _mask_name(name: str) -> str:
    return name[0] + "*" * (len(name) - 2) + name[-1] if len(name) > 2 else name[0] + "*"


def masked(inquiry: Inquiry) -> dict | None:
    """가린 계좌 (고객 화면·상담원 화면 기본): 은행 · 끝 4자리 · 예금주 가운데 가림"""
    if not inquiry.refund_account:
        return None
    return {"bank": inquiry.refund_bank, "holder": _mask_name(inquiry.refund_holder or "?"),
            "number": f"****{inquiry.refund_account[-4:]}", "registered_at": inquiry.refund_account_at}


def full(inquiry: Inquiry) -> dict | None:
    """전체 계좌 (상담원이 [번호 보기]를 누를 때만, 부르는 쪽에서 작업 기록을 남김)"""
    if not inquiry.refund_account:
        return None
    return {"bank": inquiry.refund_bank, "holder": inquiry.refund_holder, "number": inquiry.refund_account,
            "registered_at": inquiry.refund_account_at}


def needed(db: Session, inquiry: Inquiry) -> bool:
    """환불 계좌가 필요한데 아직 없음: 무통장입금 주문 + 취소·반품 문의(또는 그 요청이 반려되지 않음)"""
    if inquiry.refund_account:
        return False
    card = order_card(db, inquiry)
    if not card or not card.get("found") or card.get("payment_method") != "무통장입금" or card.get("email_match") is False:
        return False
    asked = any(t.ticket_type in ("취소", "환불") and t.status != "반려" for t in inquiry.tickets)
    category = inquiry.analysis.category if inquiry.analysis else None
    return asked or category in NEEDS_CATEGORIES
