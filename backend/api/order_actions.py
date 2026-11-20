"""문의 상세의 바로 처리: POST /api/inquiries/{id}/actions (로그인, CSRF, docs/api_spec.md)

배송지·옵션 변경, 부분 취소, 중복 승인 취소, 보상 적립금·쿠폰, 반품 회수 접수.
조건 검사와 처리는 services/order_actions.py. 권한은 문의 상세와 같음 (관리자, 또는 그 문의를 배정받은 상담원).
"""

from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.api.inquiry_admin import get_inquiry_for_user
from backend.core.dependencies import DB, LoginUser
from backend.services import order_actions

router = APIRouter(prefix="/inquiries", tags=["바로 처리"])


class ActionBody(BaseModel):
    action: Literal["address", "option", "partial_cancel", "duplicate_cancel", "points", "coupon", "return"]
    address: str | None = Field(None, max_length=200)
    option: str | None = Field(None, max_length=50)
    count: int | None = Field(None, ge=1, le=99)
    amount: int | None = Field(None, ge=0, le=1_000_000)
    reason: str | None = Field(None, max_length=50)
    coupon: str | None = Field(None, max_length=50)


@router.post("/{inquiry_id}/actions", summary="바로 처리 (로그인)")
def run_action(inquiry_id: int, body: ActionBody, request: Request, user: LoginUser, db: DB):
    inquiry = get_inquiry_for_user(db, inquiry_id, user)
    message = order_actions.run(db, request, user, inquiry, body.action, body.model_dump())
    db.commit()
    return {"ok": True, "message": message}
