"""자주 쓰는 답변 문구: 기본 문구와 '처음 한 번' 넣기.

문구는 FAQ·쇼핑몰 정책(docs/shop_policy.md)과 같은 내용만 씁니다. 관리자가 '답변 문구' 화면(/admin/templates)에서 고칩니다.
서버가 켜질 때 표가 비어 있으면 기본 문구를 넣습니다 (예전 DB도 바로 쓰이게).
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database.models import ReplyTemplate

DEFAULTS: list[tuple[str, str]] = [
    ("첫인사", "안녕하세요, 고객님. InquAI 쇼핑 고객센터입니다."),
    ("사과", "불편을 드려 죄송합니다."),
    ("취소 완료", "요청하신 주문 취소가 완료되었습니다. 결제 취소는 신용·체크카드 3~5영업일, 계좌이체·간편결제는 1~3영업일 안에 반영됩니다."),
    ("출고 후 취소 불가", "이미 출고된 주문은 취소할 수 없어, 상품을 받으신 뒤 마이페이지 > 주문내역에서 반품을 신청해 주세요."),
    ("회수 안내", "지정 택배사가 1~3영업일 안에 방문해 상품을 회수합니다. 받으신 상태 그대로 포장해 두어 주세요."),
    ("환불 일정", "반품 상품이 물류센터에 도착해 검수가 끝나면 3영업일 이내에 환불됩니다. 카드 결제는 카드사 사정에 따라 3~5영업일이 더 걸릴 수 있습니다."),
    ("파손·오배송", "파손·누락·오배송은 배송비를 저희가 부담합니다. 받으신 상품 사진을 함께 보내 주시면 더 빨리 확인해 드리겠습니다."),
    ("마무리", "추가로 궁금하신 점은 언제든 문의해 주세요. 감사합니다."),
]


def ensure_defaults(db: Session) -> int:
    """표가 비어 있으면 기본 문구를 넣고 넣은 수를 돌려줌 (커밋은 부르는 쪽에서)"""
    if db.scalar(select(func.count()).select_from(ReplyTemplate)):
        return 0
    db.add_all(ReplyTemplate(label=label, text=text, sort_order=i) for i, (label, text) in enumerate(DEFAULTS))
    return len(DEFAULTS)
