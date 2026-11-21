"""상품 옵션·재고 (시연 쇼핑몰): 옵션 변경을 재고에 맞춰 하고, 상담원·AI 초안이 재고를 근거로 안내하게.

- 상품명 괄호 안이 옵션: '와이드 데님 팬츠 (연청, 28)' → 상품 '와이드 데님 팬츠', 옵션 '연청, 28'
- 옵션이 없는 상품(세럼·선크림·프라이팬)은 옵션 변경 대상이 아님
- 재고가 0 이면 품절. 재입고 예정일이 있으면 함께 안내 (없으면 '재입고 미정')
- 재고가 바뀌는 때: 옵션 변경(새 옵션 -1, 원래 옵션 +수량), 부분 취소(+취소 수량), 취소 티켓 승인(+주문 수량)
- 진짜 재고 관리(입고·예약 재고·창고)는 쇼핑몰 시스템의 일이라 여기서는 옵션별 수량만 둡니다
- 서버가 켜질 때 표에 없는 옵션을 채움 (예전 DB도 바로 쓰이게), 시연 데이터를 다시 만들면 처음 재고로
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, object_session

from backend.database.models import Order, ProductOption, as_utc, utcnow

LOW_STOCK = 3   # 이하이면 '재고 적음'

# 상품 → [(옵션, 처음 재고, 품절일 때 재입고까지 일수 또는 None=미정)]  (상품명은 seed_data.PRODUCTS 와 같음)
CATALOG: dict[str, list[tuple[str, int, int | None]]] = {
    "오버핏 코튼 맨투맨": [("그레이, M", 12, None), ("그레이, L", 8, None), ("그레이, XL", 2, None),
                       ("블랙, M", 0, 5), ("블랙, L", 6, None), ("네이비, L", 4, None)],
    "와이드 데님 팬츠": [("연청, 26", 5, None), ("연청, 28", 9, None), ("연청, 30", 3, None),
                    ("진청, 28", 7, None), ("진청, 30", 0, 7)],
    "경량 패딩 조끼": [("블랙, S", 4, None), ("블랙, M", 10, None), ("블랙, L", 6, None), ("카키, M", 1, None),
                  ("카키, L", 0, None)],
    "니트 가디건": [("아이보리, FREE", 14, None), ("베이지, FREE", 6, None), ("차콜, FREE", 0, 10)],
    "러닝화 에어 쿠션": [("화이트, 250", 3, None), ("화이트, 260", 8, None), ("화이트, 270", 0, 4),
                    ("블랙, 260", 5, None), ("블랙, 270", 2, None)],
    "가죽 크로스백": [("브라운", 7, None), ("블랙", 3, None)],
    "무선 블루투스 이어폰": [("화이트", 15, None), ("블랙", 9, None), ("네이비", 0, 6)],
    "스테인리스 텀블러 500ml": [("실버", 30, None), ("블랙", 18, None), ("민트", 2, None)],
    "극세사 이불 세트": [("슈퍼싱글", 6, None), ("퀸", 11, None), ("킹", 0, 8)],
    "유아 내복 세트": [("90", 5, None), ("100", 9, None), ("110", 4, None), ("120", 0, None)],
    "캠핑 접이식 의자": [("카키", 6, None), ("베이지", 4, None), ("블랙", 1, None)],
}


def split_product(name: str) -> tuple[str, str | None]:
    """'와이드 데님 팬츠 (연청, 28)' → ('와이드 데님 팬츠', '연청, 28'), 옵션 없으면 (이름, None)"""
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", name)
    return (m.group(1), m.group(2)) if m else (name, None)


def ensure_catalog(db: Session, reset: bool = False) -> int:
    """표에 없는 옵션을 처음 재고로 넣음 (reset 이면 모두 지우고 처음 재고로). 넣은 수를 돌려줌, 커밋은 부르는 쪽에서"""
    if reset:
        db.execute(delete(ProductOption))
    have = {(p.product, p.option) for p in db.scalars(select(ProductOption))}
    now = utcnow()
    added = 0
    for product, options in CATALOG.items():
        for i, (option, stock, restock_days) in enumerate(options):
            if (product, option) in have:
                continue
            db.add(ProductOption(product=product, option=option, stock=stock, sort_order=i,
                                 restock_at=now + timedelta(days=restock_days) if stock == 0 and restock_days else None))
            added += 1
    db.flush()
    return added


def _rows(db: Session, product: str) -> list[ProductOption]:
    return list(db.scalars(select(ProductOption).where(ProductOption.product == product)
                           .order_by(ProductOption.sort_order, ProductOption.id)))


def choices(order: Order) -> list[dict]:
    """주문 상품의 옵션별 재고 (주문 정보 카드·옵션 변경용). 옵션이 없는 상품이면 빈 목록"""
    db = object_session(order)
    if db is None:
        return []
    base, current = split_product(order.product_name)
    return [{"option": r.option, "stock": r.stock, "sold_out": r.stock <= 0, "low": 0 < r.stock <= LOW_STOCK,
             "restock_at": as_utc(r.restock_at), "current": r.option == current} for r in _rows(db, base)]


def get(db: Session, product: str, option: str | None) -> ProductOption | None:
    if option is None:
        return None
    return db.scalar(select(ProductOption).where(ProductOption.product == product, ProductOption.option == option))


def restock(db: Session, order_product_name: str, count: int) -> None:
    """취소·부분 취소로 돌아온 수량을 재고에 더함 (옵션 표에 없는 상품이면 아무것도 안 함)"""
    base, option = split_product(order_product_name)
    row = get(db, base, option)
    if row is not None and count > 0:
        row.stock += count
        row.restock_at = None


def _kst_day(at: datetime) -> str:
    d = as_utc(at) + timedelta(hours=9)
    return f"{d.month}/{d.day}"


def describe(choice: dict) -> str:
    """'블랙, M 품절 (재입고 예정 11/26)' 처럼 한 줄 (AI 초안·화면 공통)"""
    if choice["sold_out"]:
        when = f"재입고 예정 {_kst_day(choice['restock_at'])}" if choice["restock_at"] else "재입고 미정"
        return f"{choice['option']} 품절 ({when})"
    return f"{choice['option']} 재고 {choice['stock']}개" + (" (적음)" if choice["low"] else "")
