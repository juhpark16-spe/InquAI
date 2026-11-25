"""주문·배송·고객 조회·재고 현황 API (로그인, 조회 전용, docs/api_spec.md 7-1).

    GET /api/customers?q=          고객 찾기: 이름·이메일·전화번호 뒷자리·주문번호
    GET /api/customers/{id}        고객 한 명: 주문(결제·배송 기록), 문의, 적립금·쿠폰, 불만 신호
    GET /api/orders?q=&group=      주문 찾기: 주문번호·상품·고객 이름, 출고 전·배송 중·배송 지연·배송 완료·반품·취소
    GET /api/orders/{order_number} 주문 한 건: 결제·배송 추적·반품 진행 + 고객 + 관련 문의
    GET /api/inventory?only=       상품 옵션별 재고: 품절·재고 적음·재입고 예정

- InquAI는 상담 시스템이라 고객·주문·재고를 **바꾸지 않고 보기만** 합니다. 고치는 일(배송지·옵션 변경, 취소 등)은
  지금처럼 문의 상세의 [바로 처리]·취소·교환·반품 요청 승인에서 하고, 기록이 그 문의에 남습니다.
- 권한: 관리자는 모든 고객, 상담원은 **내가 맡은 문의의 고객만** (다른 고객은 404, 문의 권한과 같은 원칙).
- 고객 상세를 열면 작업 기록에 '고객 정보 조회'(customer_view)를 남깁니다 (개인정보 조회 기록). 전화번호는 가운데를 가립니다.
"""

from datetime import timedelta

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from backend.core.dependencies import DB, LoginUser
from backend.core.errors import AppError
from backend.database.models import AdminUser, Customer, Inquiry, Order, ProductOption, Response, as_utc, utcnow
from backend.services import inquiry_context as ctx
from backend.services import inventory
from backend.services.policy import CANCELLABLE, DELAY_DAYS, SHIPPING
from backend.services.sla import OPEN_STATUSES as OPEN
from backend.services.audit import add_audit

router = APIRouter(tags=["고객 조회·재고"])


def _visible(user: AdminUser):
    """상담원이 볼 수 있는 고객: 내가 맡은 문의의 이메일과 같은 고객"""
    emails = select(func.lower(Inquiry.customer_email)).where(Inquiry.assigned_to == user.id)
    return func.lower(Customer.email).in_(emails)


@router.get("/customers", summary="고객 찾기 (로그인: 상담원은 내가 맡은 문의의 고객만)")
def list_customers(user: LoginUser, db: DB, q: str | None = Query(None, max_length=100),
                   page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    stmt = select(Customer)
    if user.role != "admin":
        stmt = stmt.where(_visible(user))
    if q and q.strip():
        term = q.strip()
        digits = "".join(ch for ch in term if ch.isdigit())
        conds = [Customer.name.contains(term), Customer.email.ilike(f"%{term}%"),
                 Customer.id.in_(select(Order.customer_id).where(Order.order_number.contains(term)))]
        if len(digits) >= 4:   # 전화번호 뒷자리 (하이픈 없이 저장된 번호도 찾도록 숫자만 비교)
            conds.append(func.replace(Customer.phone, "-", "").contains(digits))
        stmt = stmt.where(or_(*conds))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    last_order = (select(func.max(Order.ordered_at)).where(Order.customer_id == Customer.id).correlate(Customer)
                  .scalar_subquery())
    rows = db.scalars(stmt.options(selectinload(Customer.orders)).order_by(last_order.desc().nulls_last(), Customer.id)
                      .offset((page - 1) * size).limit(size)).all()
    emails = [c.email.lower() for c in rows]
    counts: dict[str, list[int]] = {}
    for email, status in db.execute(select(func.lower(Inquiry.customer_email), Inquiry.status)
                                    .where(func.lower(Inquiry.customer_email).in_(emails))):
        n = counts.setdefault(email, [0, 0])
        n[0] += 1
        n[1] += status in OPEN
    return {
        "items": [{
            "id": c.id, "name": c.name, "email": c.email, "phone": ctx.mask_phone(c.phone), "member": bool(c.password_hash),
            "orders": len(c.orders),
            "last_order_at": as_utc(max((o.ordered_at for o in c.orders), default=None)),
            "inquiries": counts.get(c.email.lower(), [0, 0])[0], "open_inquiries": counts.get(c.email.lower(), [0, 0])[1],
        } for c in rows],
        "total": total, "page": page, "size": size,
    }


@router.get("/customers/{customer_id}", summary="고객 한 명 (주문·문의·적립금·쿠폰, 조회 기록이 남음)")
def get_customer(customer_id: int, request: Request, user: LoginUser, db: DB):
    stmt = select(Customer).where(Customer.id == customer_id)
    if user.role != "admin":
        stmt = stmt.where(_visible(user))
    customer = db.scalar(stmt)
    if customer is None:
        raise AppError(404, "고객을 찾을 수 없습니다.", "NOT_FOUND")
    email = customer.email.lower()
    inquiries = db.scalars(select(Inquiry).options(selectinload(Inquiry.analysis), selectinload(Inquiry.assignee))
                           .where(func.lower(Inquiry.customer_email) == email)
                           .order_by(Inquiry.created_at.desc())).all()
    ids = [i.id for i in inquiries]
    negative_ratings = db.scalar(select(func.count()).select_from(Response)
                                 .where(Response.inquiry_id.in_(ids), Response.rating == -1)) if ids else 0
    points, coupons = ctx.points_and_coupons(db, customer)
    orders = sorted(customer.orders, key=lambda o: as_utc(o.ordered_at), reverse=True)
    # 상담원은 다른 사람이 맡은 문의의 내용은 보지 않음 (건수만)
    shown = inquiries if user.role == "admin" else [i for i in inquiries if i.assigned_to == user.id]
    add_audit(db, request, "customer_view", user, "customer", customer.id)
    db.commit()
    return {
        "id": customer.id, "name": customer.name, "email": customer.email, "phone": ctx.mask_phone(customer.phone),
        "member": bool(customer.password_hash), "since": as_utc(customer.created_at),
        **points, "coupons": coupons,
        "negative_ratings": negative_ratings or 0,
        "negative_inquiries": sum(1 for i in inquiries if i.analysis and i.analysis.sentiment == "부정"),
        "inquiry_total": len(inquiries),
        "orders": [ctx.order_detail(o, customer, customer.email) for o in orders],
        "inquiries": [{"id": i.id, "inquiry_number": i.inquiry_number, "title": i.title, "status": i.status,
                       "order_number": i.order_number, "created_at": as_utc(i.created_at),
                       "assigned_to": i.assignee.display_name if i.assignee else None} for i in shown],
    }


# 주문 묶음 (화면 탭). 배송 지연 = 출고됐는데 주문 후 DELAY_DAYS 일이 지나도 배송 완료가 아님
# (정책: 평일 출고 + 출고 후 1~2일, 주말을 넉넉히 잡아 4일. docs/shop_policy.md)
ORDER_GROUPS = {
    "ready": ("출고 전", Order.order_status.in_(CANCELLABLE)),
    "shipping": ("배송 중", Order.order_status.in_(SHIPPING)),
    "delayed": ("배송 지연", None),   # 아래에서 시간 조건으로
    "delivered": ("배송 완료", Order.order_status == "배송 완료"),
    "return": ("반품", Order.return_requested_at.is_not(None)),
    "cancel": ("취소", Order.order_status == "취소"),
}


def _group_cond(key: str):
    if key == "delayed":
        return Order.order_status.in_(SHIPPING) & (Order.ordered_at < utcnow() - timedelta(days=DELAY_DAYS))
    return ORDER_GROUPS[key][1]


def _visible_orders(user: AdminUser):
    """상담원이 볼 수 있는 주문: 내가 맡은 문의의 고객 주문 (고객 조회와 같은 원칙)"""
    return Order.customer_id.in_(select(Customer.id).where(_visible(user)))


@router.get("/orders", summary="주문 찾기 (로그인: 상담원은 내가 맡은 문의의 고객 주문만)")
def list_orders(user: LoginUser, db: DB, q: str | None = Query(None, max_length=100),
                group: str | None = Query(None, description="ready / shipping / delayed / delivered / return / cancel"),
                page: int = Query(1, ge=1), size: int = Query(30, ge=1, le=100)):
    base = select(Order).join(Customer, Order.customer_id == Customer.id)
    if user.role != "admin":
        base = base.where(_visible_orders(user))
    if q and q.strip():
        term = q.strip()
        base = base.where(or_(Order.order_number.contains(term), Order.product_name.contains(term),
                              Customer.name.contains(term), Customer.email.ilike(f"%{term}%"),
                              Order.tracking_number.contains(term)))
    count = lambda stmt: db.scalar(select(func.count()).select_from(stmt.subquery()))   # noqa: E731
    counts = {k: count(base.where(_group_cond(k))) for k in ORDER_GROUPS}
    counts["all"] = count(base)
    stmt = base.where(_group_cond(group)) if group in ORDER_GROUPS else base
    total = count(stmt)
    rows = db.scalars(stmt.options(selectinload(Order.customer)).order_by(Order.ordered_at.desc(), Order.id.desc())
                      .offset((page - 1) * size).limit(size)).all()
    # 주문번호별 문의 수·가장 최근 문의 (상담원은 내가 맡은 문의만)
    numbers = [o.order_number for o in rows]
    inq: dict[str, list[Inquiry]] = {}
    if numbers:
        istmt = select(Inquiry).where(Inquiry.order_number.in_(numbers)).order_by(Inquiry.created_at.desc())
        if user.role != "admin":
            istmt = istmt.where(Inquiry.assigned_to == user.id)
        for i in db.scalars(istmt):
            inq.setdefault(i.order_number, []).append(i)
    late = utcnow() - timedelta(days=DELAY_DAYS)
    return {
        "items": [{
            "order_number": o.order_number, "product_name": o.product_name, "amount": o.amount, "quantity": o.quantity or 1,
            "order_status": o.order_status, "shipping_status": o.shipping_status, "carrier": o.carrier,
            "tracking_number": o.tracking_number, "ordered_at": as_utc(o.ordered_at), "delivered_at": as_utc(o.delivered_at),
            "delayed": o.order_status in SHIPPING and as_utc(o.ordered_at) < late,
            "returning": o.return_requested_at is not None, "picked_up": o.picked_up_at is not None,
            "customer": {"id": o.customer.id, "name": o.customer.name},
            "inquiries": len(inq.get(o.order_number, [])),
            "latest_inquiry": ({"id": i.id, "inquiry_number": i.inquiry_number, "status": i.status}
                               if (i := (inq.get(o.order_number) or [None])[0]) else None),
        } for o in rows],
        "total": total, "counts": counts, "page": page, "size": size, "delay_days": DELAY_DAYS,
    }


@router.get("/orders/{order_number}", summary="주문 한 건 (결제·배송 추적·반품 진행, 고객, 관련 문의)")
def get_order(order_number: str, user: LoginUser, db: DB):
    stmt = select(Order).where(Order.order_number == order_number)
    if user.role != "admin":
        stmt = stmt.where(_visible_orders(user))
    order = db.scalar(stmt)
    if order is None:
        raise AppError(404, "주문을 찾을 수 없습니다.", "NOT_FOUND")
    c = order.customer
    istmt = select(Inquiry).options(selectinload(Inquiry.assignee)).where(Inquiry.order_number == order_number)
    if user.role != "admin":
        istmt = istmt.where(Inquiry.assigned_to == user.id)
    inquiries = db.scalars(istmt.order_by(Inquiry.created_at.desc())).all()
    return {
        "order": ctx.order_detail(order, c, c.email),
        "customer": {"id": c.id, "name": c.name, "member": bool(c.password_hash)},
        "inquiries": [{"id": i.id, "inquiry_number": i.inquiry_number, "title": i.title, "status": i.status,
                       "created_at": as_utc(i.created_at),
                       "assigned_to": i.assignee.display_name if i.assignee else None} for i in inquiries],
    }


@router.get("/inventory", summary="상품 옵션별 재고 (로그인, 조회 전용)")
def list_inventory(_: LoginUser, db: DB, only: str | None = Query(None, description="sold_out(품절) / low(3개 이하) / 비우면 전체"),
                   q: str | None = Query(None, max_length=100)):
    stmt = select(ProductOption)
    if q and q.strip():
        stmt = stmt.where(or_(ProductOption.product.contains(q.strip()), ProductOption.option.contains(q.strip())))
    rows = db.scalars(stmt.order_by(ProductOption.product, ProductOption.sort_order, ProductOption.id)).all()
    products: dict[str, list[dict]] = {}
    summary = {"options": 0, "sold_out": 0, "low": 0}
    for r in rows:
        sold_out, low = r.stock <= 0, 0 < r.stock <= inventory.LOW_STOCK
        summary["options"] += 1
        summary["sold_out"] += sold_out
        summary["low"] += low
        if only == "sold_out" and not sold_out or only == "low" and not low:
            continue
        products.setdefault(r.product, []).append({"option": r.option, "stock": r.stock, "sold_out": sold_out, "low": low,
                                                   "restock_at": as_utc(r.restock_at)})
    return {"products": [{"product": p, "options": o} for p, o in products.items()], "summary": summary,
            "low_stock": inventory.LOW_STOCK}
