"""시연용 DB 만들기: 개발 DB를 비우고 계정·FAQ·모의 주문과 최근 2주치 시연 문의를 넣습니다.

    python -m backend.database.seed_demo --reset

- 지우기 전에 지금 DB와 첨부 사진을 data/backups/ 에 복사해 둡니다 (되돌릴 수 있게).
- 문의는 앱이 실제로 저장하는 형식 그대로 만듭니다: 분석 결과, AI 실행 기록, 자동 답변·초안·상담원 답변,
  자동 배정·발송 작업 기록, 알림 기록, 티켓, 고객 평가, 추가 문의, 내부 메모.
  AI 모델·OpenAI는 부르지 않습니다 (빠르고, 돌릴 때마다 같은 결과).
- 지난주보다 이번 주 문의가 조금 많게 만들어 대시보드의 "지난 기간 대비"가 보이게 합니다.
- 오래된 문의는 대부분 답변 완료, 최근 문의는 미처리로 남겨 "지금 처리할 일"이 채워집니다.
- 시연 문의의 조회 비밀번호는 모두 DEMO_LOOKUP_PASSWORD (고객 화면 "내 문의 조회"에서 이메일과 함께 입력).
"""

import argparse
import random
import re
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.rules import get_route
from backend.core.config import get_settings
from backend.core.security import hash_password
from backend.database import seed_admin, seed_data
from backend.database.models import (AdminAuditLog, AdminUser, AgentLog, AnalysisResult, CustomerMessage, Customer, Inquiry,
                                     InquiryNote, Notification, Order, Response, Ticket, as_utc, utcnow)
from backend.database.session import Base, SessionLocal, engine, init_db
from backend.services import uploads
from backend.services.assignment import pick_assignee
from backend.tools.orders import shipping_summary

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parents[2]
BACKUP_DIR = ROOT / "data" / "backups"
DEMO_LOOKUP_PASSWORD = "test1234"
LLM_LABEL = "gpt-5-mini (reasoning_effort=low)"
SEED = 20261116
DAYS = 14


# 모의 주문 상품(seed_data.PRODUCTS)의 종류. 문의 내용을 주문한 상품에 맞추는 데 씀
PRODUCT_KIND = {
    "맨투맨": "옷", "데님 팬츠": "옷", "패딩 조끼": "옷", "니트 가디건": "옷", "유아 내복": "옷",
    "러닝화": "신발", "크로스백": "가방", "이어폰": "전자",
    "텀블러": "주방", "프라이팬": "주방", "이불": "침구", "캠핑": "캠핑",
    "세럼": "화장품", "선크림": "화장품",
}


def product_kind(name: str) -> str | None:
    return next((k for key, k in PRODUCT_KIND.items() if key in name), None)


def short_name(name: str) -> str:
    """'오버핏 코튼 맨투맨 (그레이, L)' → '오버핏 코튼 맨투맨' (문의 문장에 넣을 이름)"""
    return re.sub(r"\s*\(.*?\)", "", name).strip()


@dataclass
class Scenario:
    category: str
    title: str
    content: str | dict[str, str]  # 상품 종류마다 다른 문장이면 {종류: 문장}. {p} = 주문한 상품 이름
    decision: str                 # 자동 답변 / 답변 초안 / 담당자 연결
    tool: str                     # FAQ 검색 / 배송 조회 / 티켓 접수 / 상담원 이관
    answer: str                   # AI 답변(자동 답변·초안) 또는 상담원이 보낼 답변
    sentiment: str = "중립"
    urgency: str = "보통"
    decided_by: str = "LLM"
    faqs: list[str] = field(default_factory=list)
    order_status: tuple[str, ...] = ()   # 주문이 필요한 문의: 이 상태의 주문 중에서 고름
    ticket: str | None = None            # 환불 / 교환 / 취소 / 이관
    confidence: float = 0.95
    reason: str = ""
    exclude: tuple[str, ...] = ()        # 이 글자가 들어간 상품은 고르지 않음 (예: FREE 사이즈는 사이즈 교환 불가)
    delivered_days: tuple[int, int] | None = None  # 배송 완료 후 며칠 지난 문의인지 (이야기가 맞도록)

    def text_for(self, order: Order | None) -> str:
        if isinstance(self.content, dict):
            text = self.content[product_kind(order.product_name)]
        else:
            text = self.content
        return text.format(p=short_name(order.product_name)) if order else text

    @property
    def kinds(self) -> set[str] | None:
        """이 문의에 맞는 상품 종류 (None = 아무 상품)"""
        return set(self.content) if isinstance(self.content, dict) else None


S = Scenario
SCENARIOS: list[tuple[Scenario, int]] = [  # (시나리오, 뽑힐 비중)
    # ---- 자동 답변 (FAQ로 바로 답함) ----
    (S("결제", "현금영수증 신청 방법", "계좌이체로 결제했는데 현금영수증은 어떻게 받을 수 있나요?", "자동 답변", "FAQ 검색",
       "계좌이체로 결제하신 경우 주문서의 현금영수증 신청란에 휴대폰 번호나 사업자번호를 입력하시면 입금 확인 후 자동 발급됩니다. "
       "주문 후에는 마이페이지 > 주문내역 > 영수증 신청에서 신청하실 수 있습니다.", urgency="낮음", faqs=["F01"],
       reason="FAQ F01로 답할 수 있는 결제 문의"), 4),
    (S("쿠폰·적립금·회원", "쿠폰이 적용되지 않아요", "장바구니에서 쿠폰을 골랐는데 할인이 안 들어가요. 조건이 따로 있나요?", "자동 답변",
       "FAQ 검색", "쿠폰마다 최소 주문 금액, 적용 대상 상품, 사용 기간이 정해져 있습니다. 결제 화면에서 쿠폰명 옆 '조건 보기'를 누르시면 "
       "적용되지 않는 이유를 확인하실 수 있습니다.", urgency="낮음", faqs=["F05"], reason="FAQ F05 쿠폰 적용 조건"), 4),
    (S("쿠폰·적립금·회원", "적립금 언제 들어오나요", "지난주에 산 상품 적립금이 아직 안 들어왔어요. 언제 적립되나요?", "자동 답변", "FAQ 검색",
       "상품 적립금은 구매 확정 다음 날 적립됩니다. 구매 확정을 따로 하지 않으시면 배송 완료 7일 후 자동으로 확정됩니다.",
       urgency="낮음", faqs=["F06"], reason="FAQ F06 적립 시점"), 3),
    (S("배송", "제주도 배송비", "제주도도 3만원 넘으면 무료배송인가요?", "자동 답변", "FAQ 검색",
       "기본 배송비는 3,000원이며 3만원 이상 주문 시 무료입니다. 다만 제주 및 도서산간 지역은 3,000원이 추가됩니다.",
       urgency="낮음", faqs=["F15"], reason="FAQ F15 배송비"), 3),
    (S("상품", "품절 상품 재입고", "니트 아이보리 M 사이즈 품절인데 언제 다시 들어오나요?", "자동 답변", "FAQ 검색",
       "재입고 일정은 상품마다 달라 미리 안내드리기 어렵습니다. 상품 페이지의 '재입고 알림 신청'을 누르시면 입고 즉시 문자로 알려 드립니다.",
       urgency="낮음", faqs=["F11"], reason="FAQ F11 재입고"), 3),
    (S("결제", "무이자 할부 되나요", "20만원짜리 코트 사려는데 무이자 할부 몇 개월까지 되나요?", "자동 답변", "FAQ 검색",
       "5만원 이상 카드 결제 시 할부를 선택하실 수 있습니다. 무이자 할부 카드와 개월 수는 매달 바뀌므로 결제 화면의 "
       "'카드사 무이자 안내'에서 확인해 주세요.", urgency="낮음", faqs=["F03"], reason="FAQ F03 할부"), 2),
    (S("쿠폰·적립금·회원", "비밀번호를 잊어버렸어요", "로그인 비밀번호가 기억이 안 나요. 어떻게 찾나요?", "자동 답변", "FAQ 검색",
       "로그인 화면의 '비밀번호 찾기'를 누르고 가입하신 이메일이나 휴대폰 번호로 본인 인증을 하시면 새 비밀번호를 설정하실 수 있습니다.",
       urgency="낮음", faqs=["F08"], reason="FAQ F08 비밀번호 찾기"), 2),
    (S("배송", "주문한 상품 언제 와요", "며칠 전에 주문한 {p} 지금 어디쯤 왔는지 알고 싶어요.", "자동 답변", "배송 조회",
       "주문하신 상품은 현재 배송 중이며, 보통 출고 후 1~2일 안에 받으실 수 있습니다. 운송장 번호로 택배사 사이트에서 위치를 확인하실 수 있습니다.",
       faqs=["F14"], order_status=("출고", "배송 중"), reason="주문번호로 배송 상태 조회 후 안내"), 4),
    (S("교환", "맞교환 되나요", "새 상품 먼저 받고 기존 상품을 보내는 맞교환이 가능한가요?", "자동 답변", "FAQ 검색",
       "맞교환은 어렵습니다. 교환을 신청하시면 기존 상품을 먼저 회수해 검수한 뒤 2~3영업일 안에 교환 상품을 보내 드립니다.",
       urgency="낮음", faqs=["F31"], reason="FAQ F31 맞교환"), 2),
    (S("기타", "고객센터 운영 시간", "전화 상담은 몇 시까지 되나요?", "자동 답변", "FAQ 검색",
       "전화 상담은 평일 오전 10시부터 오후 5시까지(점심시간 12시~1시 제외) 운영하며 주말과 공휴일은 쉽니다. 1:1 문의는 24시간 남기실 수 있습니다.",
       urgency="낮음", faqs=["F44"], reason="FAQ F44 운영 시간"), 2),

    # ---- 답변 초안 (AI가 쓰고 상담원이 확인) ----
    (S("반품·환불", "환불 금액이 적게 들어왔어요", "{p} 반품했는데 환불이 결제한 금액보다 6천원 적게 들어왔어요. 왜 그런가요?", "답변 초안",
       "FAQ 검색", "단순 변심 반품은 왕복 배송비 6,000원이 환불 금액에서 차감됩니다. 차감 내역은 마이페이지 > 주문내역 > 환불 상세에서 "
       "확인하실 수 있습니다. 불량으로 반품하신 경우라면 말씀해 주세요. 확인 후 차감액을 돌려드리겠습니다.", sentiment="부정",
       faqs=["F35"], order_status=("배송 완료",), reason="FAQ F35로 설명 가능하나 불량 여부 확인이 필요해 초안", delivered_days=(3, 30)), 3),
    (S("주문 취소", "수량 일부만 취소하고 싶어요", "{p} 2개 주문했는데 1개만 취소할 수 있을까요?", "답변 초안", "티켓 접수",
       "출고 전이라 부분 취소가 가능합니다. 요청하신 1개의 취소를 접수했으며, 무료배송 기준(3만원) 아래가 되면 배송비 3,000원이 "
       "차감될 수 있습니다.", faqs=["F28"], order_status=("결제 완료", "상품 준비 중"), ticket="취소",
       reason="부분 취소 접수, 배송비 차감 여부 확인 필요"), 2),
    (S("상품", "사이즈 추천 부탁드려요", "평소 66 입는데 이 원피스 M이 맞을까요? 어깨가 좀 넓은 편이에요.", "답변 초안", "FAQ 검색",
       "상품 페이지 하단 '사이즈 정보'에서 실측 사이즈를 확인하실 수 있습니다. 어깨가 넓은 편이시면 어깨너비 실측과 가지고 계신 옷을 "
       "비교해 보시길 권해 드립니다.", faqs=["F12"], reason="개인 체형 문의라 초안 후 상담원 확인"), 2),

    # ---- 담당자 연결 (사람이 처리) ----
    (S("배송", "상품이 파손되어 왔어요", {
        "주방": "택배 상자를 열어보니 {p} 상품이 찌그러져 있었어요. 너무 속상하네요. 어떻게 해야 하나요?",
        "캠핑": "택배 상자를 열어보니 {p} 다리 하나가 휘어져 있었어요. 너무 속상하네요. 어떻게 해야 하나요?",
        "화장품": "택배 상자를 열어보니 {p} 용기가 깨져서 내용물이 다 샜어요. 너무 속상하네요. 어떻게 해야 하나요?",
        "가방": "받은 {p} 가죽에 찍힌 자국이 크게 나 있어요. 배송 중에 상한 것 같아요. 어떻게 해야 하나요?",
        "전자": "받은 {p} 충전 케이스가 깨져서 왔어요. 너무 속상하네요. 어떻게 해야 하나요?"},
       "담당자 연결", "상담원 이관", "불편을 드려 정말 죄송합니다. 택배사 파손으로 확인되어 새 상품으로 바로 교환해 드리고, "
       "파손된 상품은 회수하지 않으셔도 됩니다. 내일 출고 예정입니다.", sentiment="부정", urgency="높음", decided_by="규칙",
       order_status=("배송 완료",), ticket="교환", reason="파손 문의 → 담당자 확인 (규칙)", delivered_days=(0, 4)), 3),
    (S("반품·환불", "환불이 아직 안 들어왔어요", "{p} 반품한 지 일주일이 넘었는데 아직 환불이 안 됐어요. 빨리 처리해 주세요.",
       "담당자 연결", "티켓 접수", "기다리시게 해서 죄송합니다. 확인해 보니 물류센터 검수가 늦어졌습니다. 오늘 환불 처리했으며 "
       "카드사 반영까지 3~5영업일 걸릴 수 있습니다.", sentiment="부정", urgency="높음", decided_by="규칙",
       order_status=("배송 완료",), ticket="환불", reason="돈 관련 부정 문의 → 긴급, 담당자 연결 (규칙)", delivered_days=(9, 30)), 3),
    (S("결제", "결제가 두 번 됐어요", "주문은 하나인데 카드 결제 문자가 두 번 왔어요. 확인 부탁드립니다.", "담당자 연결", "상담원 이관",
       "확인해 보니 결제 오류로 중복 승인이 되었습니다. 한 건은 오늘 승인 취소했으며 카드사에 따라 3~5영업일 안에 반영됩니다. "
       "불편을 드려 죄송합니다.", sentiment="부정", urgency="높음", decided_by="규칙", reason="결제 오류 의심 → 긴급 (규칙)"), 2),
    (S("배송", "배송 완료인데 못 받았어요", "{p} 배송 완료라고 나오는데 문 앞에도 경비실에도 없어요.", "담당자 연결", "상담원 이관",
       "택배사에 확인해 보니 옆 동 경비실로 잘못 배달되었습니다. 기사님이 오늘 중으로 다시 가져다 드린다고 합니다.",
       sentiment="부정", urgency="높음", order_status=("배송 완료",), reason="분실 의심 → 택배사 확인 필요", delivered_days=(0, 3)), 2),
    (S("교환", "사이즈 교환 신청", {
        "옷": "{p} 받았는데 생각보다 작아요. 한 치수 큰 걸로 교환하고 싶어요.",
        "신발": "{p} 신어 보니 발볼이 끼어요. 한 치수 큰 걸로 교환하고 싶어요."}, "담당자 연결", "티켓 접수",
       "교환 접수했습니다. 1~3영업일 안에 기사님이 방문해 회수하고, 검수 후 큰 사이즈로 보내 드리겠습니다.",
       order_status=("배송 완료",), ticket="교환", reason="교환 접수 → 담당자 처리", exclude=("FREE",), delivered_days=(0, 6)), 3),
    (S("주문 취소", "주문 취소해 주세요", "{p} 주문이 실수로 두 번 들어갔어요. 하나 취소해 주세요.", "담당자 연결", "티켓 접수",
       "중복 주문 건 취소 처리했습니다. 결제하신 수단으로 1~3영업일 안에 환불됩니다.",
       order_status=("결제 완료", "상품 준비 중"), ticket="취소", reason="취소 요청 접수"), 3),
    (S("기타", "단체 주문 문의", "회사 행사용으로 같은 티셔츠 80장 정도 사려고 하는데 할인이 되나요?", "담당자 연결", "상담원 이관",
       "단체 주문 문의 감사합니다. 50장 이상은 담당 부서에서 견적을 따로 드립니다. 원하시는 색상·사이즈 수량을 알려 주시면 견적서를 보내 드리겠습니다.",
       urgency="낮음", decided_by="규칙", reason="FAQ에 없는 기타 문의 → 담당자 (규칙)"), 1),
    (S("상품", "제품 불량 같아요", {
        "전자": "받은 {p} 충전이 안 되고 전원도 안 켜져요. 불량인 것 같습니다.",
        "옷": "받은 {p} 박음질이 처음부터 뜯어져 있어요. 불량인 것 같습니다.",
        "신발": "받은 {p} 밑창이 한쪽만 들떠 있어요. 불량인 것 같습니다.",
        "가방": "받은 {p} 지퍼가 걸려서 열리지 않아요. 불량인 것 같습니다.",
        "주방": "받은 {p} 처음부터 흠집이 나 있고 마감이 불량이에요. 불량인 것 같습니다.",
        "캠핑": "받은 {p} 다리 고정 부분이 헐거워서 펴지지 않아요. 불량인 것 같습니다.",
        "침구": "받은 {p} 커버 지퍼가 고장 나 있고 솔기도 터져 있어요. 불량인 것 같습니다.",
        "화장품": "받은 {p} 펌프가 눌리지 않아서 쓸 수가 없어요. 불량인 것 같습니다."}, "담당자 연결", "상담원 이관",
       "불편을 드려 죄송합니다. 초기 불량으로 확인되어 새 제품으로 교환해 드리겠습니다. 회수 기사님이 방문할 예정입니다.",
       sentiment="부정", faqs=["F13"], order_status=("배송 완료",), reason="불량 의심 → 담당자 확인", delivered_days=(0, 25)), 2),
    (S("쿠폰·적립금·회원", "적립금이 사라졌어요", "분명히 5천원 있었는데 오늘 보니 적립금이 없어졌어요.", "담당자 연결", "상담원 이관",
       "확인해 보니 적립일로부터 1년이 지나 소멸된 적립금입니다. 소멸 7일 전 안내 문자가 발송되었지만 이번에는 사과의 의미로 "
       "3,000원을 다시 적립해 드렸습니다.", sentiment="부정", confidence=0.72, decided_by="규칙",
       reason="유형 확신도 0.72 < 0.8 → 담당자 연결 (규칙)"), 2),
]

FOLLOW_UPS = ["답변 감사합니다. 그런데 한 가지 더 여쭤봐도 될까요? 다른 색상으로도 교환이 되나요?",
              "알려주신 대로 했는데 아직 해결이 안 됐어요. 다시 확인 부탁드립니다."]
NOTES = ["택배사에 사고 접수함. 회신 오면 고객 안내 예정", "고객과 통화 완료. 교환으로 진행하기로 함",
         "카드사 승인 내역 확인 요청함 (내일 오전 회신)"]


def backup(stamp: str) -> Path | None:
    """지금 SQLite DB와 첨부 사진을 data/backups/ 에 복사 (서버가 켜져 있어도 안전한 SQLite 백업 API 사용)"""
    url = get_settings().resolved_database_url
    if not url.startswith("sqlite:///"):
        raise SystemExit("시연 DB 초기화는 개발용 SQLite에서만 합니다. (DATABASE_URL 확인)")
    db_file = Path(url.removeprefix("sqlite:///"))
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = None
    if db_file.exists():
        target = BACKUP_DIR / f"inquai-{stamp}.db"
        with sqlite3.connect(db_file) as src, sqlite3.connect(target) as dst:
            src.backup(dst)
    upload_dir = Path(uploads.UPLOAD_DIR)
    if upload_dir.exists() and any(upload_dir.iterdir()):
        shutil.move(str(upload_dir), BACKUP_DIR / f"uploads-{stamp}")
    return target


def _kst_time(day: datetime, rng: random.Random) -> datetime:
    """그날 KST 9시~22시 사이 (오후에 조금 더 많게)"""
    hour = rng.choices(range(9, 23), weights=[2, 3, 4, 4, 3, 4, 4, 4, 3, 3, 3, 2, 2, 1])[0]
    return day.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))


def _pick_order(db: Session, sc: Scenario, at: datetime, used: set[int], rng: random.Random) -> Order | None:
    """시나리오에 맞는 상태·상품 종류이고, 문의 시각(at) 전에 주문(배송 완료)된 주문 하나 (없으면 None).
    한 주문은 문의 하나에만 씀 (같은 주문에 파손·불량·환불 문의가 겹치지 않게)"""
    orders = db.scalars(select(Order).where(Order.order_status.in_(sc.order_status)).order_by(Order.id)).all()
    orders = [o for o in orders if o.id not in used
              and as_utc(o.ordered_at) < at and (o.delivered_at is None or as_utc(o.delivered_at) < at)]
    if sc.delivered_days:
        lo, hi = sc.delivered_days
        orders = [o for o in orders if o.delivered_at
                  and timedelta(days=lo) <= at - as_utc(o.delivered_at) <= timedelta(days=hi)]
    if sc.kinds is not None:
        orders = [o for o in orders if product_kind(o.product_name) in sc.kinds]
    orders = [o for o in orders if not any(x in o.product_name for x in sc.exclude)]
    return rng.choice(orders) if orders else None


def seed_inquiries(db: Session, *, now: datetime | None = None, days: int = DAYS, seed: int = SEED) -> int:
    """최근 days일치 시연 문의를 만듭니다 (커밋은 부르는 쪽에서). 만든 문의 수를 돌려줌"""
    rng = random.Random(seed)
    now = now or utcnow()
    settings = get_settings()
    model_version = f"{settings.category_model_version}+{settings.sentiment_model_version}"
    password_hash = hash_password(DEMO_LOOKUP_PASSWORD)
    customers = db.scalars(select(Customer).order_by(Customer.id)).all()
    scenarios, weights = zip(*SCENARIOS)
    today = now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)

    # 날짜별 문의 수: 지난주 2~4건, 이번 주 3~6건 (오늘은 지금 시각까지만)
    plan: list[datetime] = []
    for back in range(days - 1, -1, -1):
        day = today - timedelta(days=back)
        n = rng.randint(2, 4) if back >= 7 else rng.randint(3, 6)
        times = sorted(_kst_time(day, rng) for _ in range(n))
        plan += [t.astimezone(timezone.utc) for t in times if t.astimezone(timezone.utc) < now - timedelta(minutes=10)]

    seq: dict[str, int] = {}
    used_orders: set[int] = set()
    follow_ups = notes = 0
    admin = db.scalar(select(AdminUser).where(AdminUser.role == "admin").order_by(AdminUser.id))
    # 시연에서 꼭 보여야 할 미처리 문의: 마지막(가장 최근) 몇 건은 긴급·초안 문의로 고정
    by_title = {sc.title: sc for sc in scenarios}
    forced = {len(plan) - 1: "상품이 파손되어 왔어요", len(plan) - 3: "환불 금액이 적게 들어왔어요",
              len(plan) - 5: "환불이 아직 안 들어왔어요"}
    # 고정 문의의 주문을 먼저 정해 둠 (앞 문의들이 맞는 주문을 다 써 버리지 않게)
    reserved = {}
    for idx, title in forced.items():
        if 0 <= idx < len(plan) and (o := _pick_order(db, by_title[title], plan[idx], used_orders, rng)):
            reserved[idx] = o
            used_orders.add(o.id)
    for idx, created in enumerate(plan):
        sc: Scenario = by_title[forced[idx]] if idx in reserved else rng.choices(scenarios, weights=weights)[0]
        order = reserved.get(idx) or (_pick_order(db, sc, created, used_orders, rng) if sc.order_status else None)
        while sc.order_status and order is None:  # 맞는 주문이 없으면 다른 시나리오로
            sc = rng.choices(scenarios, weights=weights)[0]
            order = _pick_order(db, sc, created, used_orders, rng) if sc.order_status else None
        if order:
            used_orders.add(order.id)
        customer = order.customer if order else rng.choice(customers)
        day_key = created.astimezone(KST).strftime("%Y%m%d")
        seq[day_key] = seq.get(day_key, 0) + 1
        age = now - created

        inquiry = Inquiry(
            inquiry_number=f"INQ-{day_key}-{seq[day_key]:04d}", customer_name=customer.name,
            customer_email=customer.email, lookup_password_hash=password_hash,
            order_number=order.order_number if order else None, title=sc.title,
            content=sc.text_for(order) + (f" (주문번호 {order.order_number})" if order else ""),
            privacy_agreed_at=created, created_at=created, updated_at=created, status="접수",
        )
        db.add(inquiry)
        db.flush()

        # ---- AI 분석·판단 ----
        llm = sc.decided_by == "LLM"
        latency = rng.randint(5200, 11500) if llm else rng.randint(20, 60)
        decided_at = created + timedelta(milliseconds=latency)
        sent_conf = round(rng.uniform(0.82, 0.98), 4)
        conf = sc.confidence if sc.confidence < 0.8 else round(rng.uniform(0.86, 0.99), 4)
        db.add(AnalysisResult(
            inquiry_id=inquiry.id, category=sc.category, confidence=conf,
            sentiment=sc.sentiment, sentiment_confidence=sent_conf, urgency=sc.urgency, route=get_route(sc.category),
            decision=sc.decision, decided_by=sc.decided_by, decision_reason=sc.reason, model_version=model_version,
            scores={"category": {sc.category: conf}, "sentiment": {sc.sentiment: sent_conf}}, created_at=created,
        ))
        tool_output = ({"faq_ids": sc.faqs} if sc.tool == "FAQ 검색" else shipping_summary(order) if sc.tool == "배송 조회" and order
                       else {"ticket_type": sc.ticket} if sc.ticket else {"message": "상담원 확인 필요"})
        ai_text = sc.answer if sc.decision != "담당자 연결" else None
        db.add(AgentLog(
            inquiry_id=inquiry.id, category=sc.category, confidence=conf, decision=sc.decision,
            decided_by=sc.decided_by, selected_tool=sc.tool, tool_success=True, tool_output=tool_output,
            retrieved_faqs=[[f, round(rng.uniform(0.62, 0.83), 4)] for f in sc.faqs], used_faq_ids=sc.faqs,
            reason=sc.reason, response_text=ai_text, llm_model=LLM_LABEL if llm else None,
            tokens={"input": rng.randint(1500, 2300), "output": rng.randint(150, 380), "calls": 2} if llm else {"calls": 0},
            latency_ms=latency, created_at=decided_at, steps=_steps(sc),
        ))

        if sc.decision == "자동 답변":
            inquiry.status = "자동 처리"
            r = Response(inquiry_id=inquiry.id, draft_text=sc.answer, generated_by="llm", used_faq_ids=sc.faqs,
                         grounded=True, status="발송", approved_at=decided_at, created_at=decided_at)
            _rate(r, now, decided_at, rng)
            db.add(r)
            _notify(db, inquiry, decided_at)
            inquiry.updated_at = decided_at
            continue

        # ---- 사람이 볼 문의: 배정 ----
        inquiry.status = "검토 대기" if sc.decision == "답변 초안" else "담당자 처리"
        agent, rule, load = pick_assignee(db, sc.category)
        if agent:
            inquiry.assigned_to = agent.id
            db.add(AdminAuditLog(admin_id=None, action="auto_assign", target_type="inquiry", target_id=inquiry.id,
                                 created_at=decided_at, detail={"assigned_to": agent.id, "category": sc.category,
                                                                "rule": rule, "load": load}))
        draft = None
        if sc.decision == "답변 초안":
            draft = Response(inquiry_id=inquiry.id, draft_text=sc.answer, generated_by="llm", used_faq_ids=sc.faqs,
                             grounded=True, status="초안", created_at=decided_at)
            db.add(draft)
        ticket = None
        if sc.ticket:
            ticket = Ticket(inquiry_id=inquiry.id, order_id=order.id if order else None, ticket_type=sc.ticket,
                            reason=sc.reason, status="접수", created_at=decided_at)
            db.add(ticket)

        # 처리 여부: 하루 넘은 문의는 대부분 완료, 반나절 안쪽은 미처리 (일부는 기한 초과로 남김)
        p_done = 0.95 if age > timedelta(days=1) else 0.5 if age > timedelta(hours=5) else 0.0
        if agent and notes < len(NOTES) and sc.urgency == "높음" and rng.random() < 0.4:
            db.add(InquiryNote(inquiry_id=inquiry.id, author_id=agent.id, text=NOTES[notes],
                               created_at=decided_at + timedelta(minutes=rng.randint(20, 90))))
            notes += 1
        done = rng.random() < p_done
        if not agent and done and admin:
            # 담당 상담원이 없는 유형(기타 등)은 관리자가 직접 맡아 처리한 것으로
            at = decided_at + timedelta(minutes=rng.randint(30, 180))
            before = {"assigned_to": None, "status": inquiry.status}
            inquiry.assigned_to = admin.id
            db.add(AdminAuditLog(admin_id=admin.id, action="assign", target_type="inquiry", target_id=inquiry.id,
                                 created_at=at, detail={"before": before,
                                                        "after": {"assigned_to": admin.id, "status": inquiry.status}}))
            agent = admin
        if not agent or not done:
            inquiry.updated_at = decided_at
            continue

        limit = 4 if sc.urgency == "높음" else 20
        sent_at = created + timedelta(hours=rng.uniform(0.5, limit), minutes=rng.randint(0, 59))
        sent_at = min(sent_at, now - timedelta(minutes=5))
        if draft:  # AI 초안을 승인 (30%는 고쳐서)
            edited = rng.random() < 0.3
            draft.final_text = sc.answer + (" 추가로 궁금하신 점은 언제든 문의해 주세요." if edited else "")
            draft.status, draft.approved_by, draft.approved_at, draft.is_edited = "발송", agent.id, sent_at, edited
            response = draft
        else:  # 상담원이 직접 작성
            response = Response(inquiry_id=inquiry.id, draft_text=sc.answer, final_text=sc.answer,
                                generated_by="agent_user", used_faq_ids=[], status="발송", approved_by=agent.id,
                                approved_at=sent_at, created_at=sent_at - timedelta(minutes=2))
            db.add(response)
            db.flush()
            db.add(AdminAuditLog(admin_id=agent.id, action="response_create", target_type="inquiry",
                                 target_id=inquiry.id, created_at=sent_at - timedelta(minutes=2),
                                 detail={"response_id": response.id}))
        db.flush()
        db.add(AdminAuditLog(admin_id=agent.id, action="response_approve", target_type="inquiry", target_id=inquiry.id,
                             created_at=sent_at, detail={"response_id": response.id, "generated_by": response.generated_by,
                                                         "is_edited": response.is_edited, "after": "완료"}))
        if ticket:
            ticket.status, ticket.handled_by, ticket.handled_at = "승인", agent.id, sent_at
        _rate(response, now, sent_at, rng)
        _notify(db, inquiry, sent_at)
        inquiry.status, inquiry.updated_at = "완료", sent_at

        # 답변을 보고 다시 물어본 고객 (다시 담당자 처리로)
        if follow_ups < len(FOLLOW_UPS) and age > timedelta(days=2) and rng.random() < 0.15:
            at = sent_at + timedelta(hours=rng.randint(2, 20))
            db.add(CustomerMessage(inquiry_id=inquiry.id, content=FOLLOW_UPS[follow_ups], created_at=at))
            inquiry.status, inquiry.updated_at = "담당자 처리", at
            follow_ups += 1

    db.flush()
    return len(plan)


def _steps(sc: Scenario) -> list[str]:
    """에이전트 그래프(graph.py)에서 이 시나리오가 지나가는 노드 이름"""
    steps = ["FAQ 검색", "규칙 판단"] + (["LLM 판단"] if sc.decided_by == "LLM" else []) + ["주문 본인 확인"]
    if sc.decision == "자동 답변":
        return steps + ["FAQ 답변", "답변 검사"]
    return steps + [{"FAQ 검색": "FAQ 기록"}.get(sc.tool, sc.tool)]


def _rate(response: Response, now: datetime, sent_at: datetime, rng: random.Random) -> None:
    """하루 지난 답변의 60%에 고객 평가 (80%는 도움됨)"""
    if now - sent_at > timedelta(days=1) and rng.random() < 0.6:
        response.rating = 1 if rng.random() < 0.8 else -1
        response.rated_at = sent_at + timedelta(hours=rng.randint(1, 20))


def _notify(db: Session, inquiry: Inquiry, at: datetime) -> None:
    db.add(Notification(inquiry_id=inquiry.id, channel="email", recipient=inquiry.customer_email,
                        subject="[InquAI 쇼핑] 문의하신 내용에 답변이 등록되었습니다",
                        body=f"{inquiry.customer_name}님, 문의({inquiry.inquiry_number})에 답변이 등록되었습니다.",
                        status="기록", created_at=at))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="시연용 DB 만들기 (개발 DB를 비우고 다시 채움)")
    p.add_argument("--reset", action="store_true", help="이 옵션이 있어야 실행합니다 (지금 DB를 비움)")
    args = p.parse_args()
    if not args.reset:
        raise SystemExit("지금 개발 DB를 비우고 시연 데이터로 다시 채웁니다. 계속하려면 --reset 을 붙여 실행하세요.")

    seed_admin.check_passwords()
    stamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    saved = backup(stamp)
    if saved:
        print(f"[백업] {saved.relative_to(ROOT)}")

    Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as db:
        seed_admin.seed_accounts(db)
        seed_data.seed_faqs(db)
        seed_data.seed_orders(db, reset=False)
        db.flush()
        seed_admin.seed_customer_passwords(db)
        n = seed_inquiries(db)
        db.commit()
    print(f"[시연 문의] 최근 {DAYS}일 {n}건 · 조회 비밀번호 {DEMO_LOOKUP_PASSWORD} (고객 이메일 customerNN@example.com)")
    print("서버가 켜져 있다면 다시 켜 주세요 (FAQ 검색이 새 DB를 읽도록).")


if __name__ == "__main__":
    main()
