"""쇼핑몰 로그인 연동 시연 API (고객, 4주차, docs/api_spec.md 3-1장).

실제 서비스에서는 쇼핑몰이 고객 로그인을 맡고, 고객센터(InquAI)는 로그인한 고객 정보를 넘겨받습니다.
시연에서는 모의 고객(customerNN@example.com)으로 로그인해 그 흐름을 흉내 냅니다. 회원가입·비밀번호 찾기는 없습니다.

    POST /api/shop/login                         이메일 + 비밀번호 → 고객 쿠키 (관리자 로그인과 따로)
    POST /api/shop/logout
    GET  /api/shop/me                            로그인한 고객 (없으면 401)
    GET  /api/shop/orders                        내 주문 (주문별 문의 수)
    GET  /api/shop/inquiries                     내 문의 (조회 비밀번호 없이)
    POST /api/shop/inquiries/{번호}/follow-up     추가 문의
    POST /api/shop/answers/{id}/rating           답변 평가

문의 등록은 기존 POST /api/inquiries 를 그대로 쓰고, 로그인 상태면 이름·이메일을 계정 정보로 채웁니다.
"""

from collections import Counter

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select

from backend.core.dependencies import DB, ShopCustomer
from backend.core.errors import AppError
from backend.core.rate_limit import FailureLock, rate_limit
from backend.core.security import clear_shop_cookies, create_shop_token, set_shop_cookies, verify_password
from backend.database.models import Customer, Inquiry
from backend.schemas.common import UTCDateTime
from backend.schemas.inquiry import InquiryLookupResult, RefundAccountIn, fill_follow_up, normalize_order_number
from backend.services import sla
from backend.services.inquiries import add_follow_up, find_customer_inquiries, public_view, rate_answer

router = APIRouter(prefix="/shop", tags=["쇼핑몰 연동 (고객 로그인)"])

# 같은 이메일로 15분 안에 5번 틀리면 15분 동안 막음
login_failures = FailureLock(limit=5, window_seconds=15 * 60)
LOGIN_FAILED = "이메일 또는 비밀번호가 맞지 않습니다."


class ShopLogin(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def _clean(cls, v: str) -> str:
        return v.strip().lower()


class ShopMe(BaseModel):
    name: str
    email: str


class ShopOrder(BaseModel):
    order_number: str
    product_name: str
    amount: int
    order_status: str
    shipping_status: str | None
    ordered_at: UTCDateTime
    delivered_at: UTCDateTime | None
    inquiry_count: int
    payment_method: str | None = None   # 무통장입금이면 문의하기에서 환불 계좌 칸을 펼침


class FollowUpBody(BaseModel):
    content: str = Field(default="", max_length=2000)   # 사진·주문번호만 보낼 때는 비워도 됨
    attachment_tokens: list[str] = Field(default_factory=list, max_length=3)
    order_number: str | None = Field(default=None, max_length=30)   # 처음 문의에 주문번호가 없을 때만
    refund_account: RefundAccountIn | None = None   # 환불 계좌 (무통장입금 주문 취소·반품, 글과 따로)

    @field_validator("order_number", mode="before")
    @classmethod
    def _order_number(cls, v):
        return normalize_order_number(v) if isinstance(v, str) else v

    @field_validator("content", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _fill(self):
        return fill_follow_up(self)


class RatingBody(BaseModel):
    helpful: bool


def _me(c: Customer) -> dict:
    return {"name": c.name, "email": c.email}


def _my_inquiry(db, customer: Customer, inquiry_number: str) -> Inquiry:
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == inquiry_number,
                                              Inquiry.customer_email == customer.email))
    if inquiry is None:
        raise AppError(404, "내 문의에서 찾을 수 없습니다.", "NOT_FOUND")
    return inquiry


@router.post("/login", response_model=ShopMe, summary="고객 로그인 (쇼핑몰 연동 시연)",
             dependencies=[Depends(rate_limit("shop_login", 10, 60))])
def login(body: ShopLogin, response: Response, db: DB):
    if login_failures.is_locked(body.email):
        raise AppError(429, "비밀번호를 여러 번 틀려 15분 동안 로그인할 수 없습니다.", "TOO_MANY_REQUESTS")
    customer = db.scalar(select(Customer).where(func.lower(Customer.email) == body.email))
    # 없는 이메일이어도 같은 시간이 걸리게 해시 검사를 함 (이메일 가입 여부를 알 수 없게)
    if not verify_password(body.password, customer.password_hash if customer else None):
        login_failures.fail(body.email)
        raise AppError(401, LOGIN_FAILED, "INVALID_CREDENTIALS")
    set_shop_cookies(response, create_shop_token(customer.id))
    return _me(customer)


@router.post("/logout", status_code=204, summary="고객 로그아웃")
def logout(response: Response):
    clear_shop_cookies(response)


@router.get("/me", response_model=ShopMe, summary="로그인한 고객")
def me(customer: ShopCustomer):
    return _me(customer)


@router.get("/orders", response_model=list[ShopOrder], summary="내 주문 (최신순)")
def my_orders(customer: ShopCustomer, db: DB):
    counts = Counter(db.scalars(select(Inquiry.order_number).where(Inquiry.customer_email == customer.email,
                                                                   Inquiry.order_number.is_not(None))))
    orders = sorted(customer.orders, key=lambda o: o.ordered_at, reverse=True)
    return [{**{k: getattr(o, k) for k in ("order_number", "product_name", "amount", "order_status",
                                            "shipping_status", "ordered_at", "delivered_at", "payment_method")},
             "inquiry_count": counts[o.order_number]} for o in orders]


@router.get("/inquiries", response_model=InquiryLookupResult, summary="내 문의 (조회 비밀번호 없이)")
def my_inquiries(customer: ShopCustomer, db: DB):
    return {"items": [public_view(i) for i in find_customer_inquiries(db, customer.email)],
            "notice": sla.CUSTOMER_NOTICE}


@router.post("/inquiries/{inquiry_number}/follow-up", status_code=201, summary="추가 문의",
             dependencies=[Depends(rate_limit("follow_up", 5, 60))])
def follow_up(inquiry_number: str, body: FollowUpBody, customer: ShopCustomer, db: DB):
    inquiry = _my_inquiry(db, customer, inquiry_number)
    if body.order_number and not any(o.order_number == body.order_number for o in customer.orders):
        raise AppError(422, "내 주문 목록에 없는 주문번호입니다.", "ORDER_NOT_FOUND")
    add_follow_up(db, inquiry, body.content, body.attachment_tokens, body.order_number, body.refund_account)
    return {"inquiry_number": inquiry.inquiry_number, "status": inquiry.status,
            "message": "추가 문의가 접수되었습니다. " + sla.CUSTOMER_NOTICE}


@router.post("/answers/{response_id}/rating", summary="답변 평가",
             dependencies=[Depends(rate_limit("rating", 20, 60))])
def rate(response_id: int, inquiry_number: str, body: RatingBody, customer: ShopCustomer, db: DB):
    r = rate_answer(db, _my_inquiry(db, customer, inquiry_number), response_id, body.helpful)
    return {"id": r.id, "rating": r.rating}
