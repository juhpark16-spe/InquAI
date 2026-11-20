"""자주 쓰는 답변 문구 API (docs/api_spec.md).

    GET    /api/reply-templates              답변 칸용: 사용 중인 문구 (로그인). 관리자는 ?all=true 로 숨긴 문구까지
    POST   /api/reply-templates              문구 추가 (관리자)
    PATCH  /api/reply-templates/{id}         이름·문장·사용 여부 변경 (관리자)
    DELETE /api/reply-templates/{id}         삭제 (관리자)
    PUT    /api/reply-templates/order        순서 바꾸기: id 목록 순서대로 (관리자)
모든 변경은 작업 기록(감사 로그)에 남깁니다.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from backend.core.dependencies import DB, AdminOnly, LoginUser
from backend.core.errors import AppError
from backend.database.models import ReplyTemplate
from backend.services.audit import add_audit

router = APIRouter(prefix="/reply-templates", tags=["답변 문구"])


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    label: str
    text: str
    sort_order: int
    is_active: bool


class TemplateIn(BaseModel):
    label: str = Field(min_length=1, max_length=20)
    text: str = Field(min_length=2, max_length=500)

    @field_validator("label", "text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("빈 값은 저장할 수 없습니다.")
        return v


class TemplatePatch(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=20)
    text: str | None = Field(None, min_length=2, max_length=500)
    is_active: bool | None = None


class TemplateOrder(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=100)


def _get(db, template_id: int) -> ReplyTemplate:
    t = db.get(ReplyTemplate, template_id)
    if t is None:
        raise AppError(404, "문구를 찾을 수 없습니다.", "NOT_FOUND")
    return t


@router.get("", response_model=list[TemplateOut], summary="답변 문구 목록 (로그인)")
def list_templates(user: LoginUser, db: DB, all: bool = False):
    stmt = select(ReplyTemplate).order_by(ReplyTemplate.sort_order, ReplyTemplate.id)
    if not (all and user.role == "admin"):
        stmt = stmt.where(ReplyTemplate.is_active.is_(True))
    return db.scalars(stmt).all()


@router.post("", response_model=TemplateOut, status_code=201, summary="답변 문구 추가 (관리자)")
def create_template(body: TemplateIn, request: Request, admin: AdminOnly, db: DB):
    last = db.scalar(select(func.max(ReplyTemplate.sort_order))) or 0
    t = ReplyTemplate(label=body.label, text=body.text, sort_order=last + 1)
    db.add(t)
    db.flush()
    add_audit(db, request, "template_create", admin, "reply_template", t.id, label=t.label)
    db.commit()
    db.refresh(t)
    return t


@router.put("/order", response_model=list[TemplateOut], summary="답변 문구 순서 바꾸기 (관리자)")
def reorder_templates(body: TemplateOrder, request: Request, admin: AdminOnly, db: DB):
    rows = {t.id: t for t in db.scalars(select(ReplyTemplate))}
    if set(body.ids) != set(rows) or len(body.ids) != len(rows):
        raise AppError(422, "모든 문구의 id 를 한 번씩 보내 주세요.", "INVALID_PARAM")
    for i, tid in enumerate(body.ids):
        rows[tid].sort_order = i
    add_audit(db, request, "template_reorder", admin, "reply_template", None, order=body.ids)
    db.commit()
    return [rows[i] for i in body.ids]


@router.patch("/{template_id}", response_model=TemplateOut, summary="답변 문구 수정 (관리자)")
def update_template(template_id: int, body: TemplatePatch, request: Request, admin: AdminOnly, db: DB):
    t = _get(db, template_id)
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for key in ("label", "text"):
        if key in changes:
            changes[key] = changes[key].strip()
            if not changes[key]:
                raise AppError(422, "빈 값은 저장할 수 없습니다.", "INVALID_PARAM")
    before = {k: getattr(t, k) for k in changes}
    for k, v in changes.items():
        setattr(t, k, v)
    if before != changes:
        add_audit(db, request, "template_update", admin, "reply_template", t.id, label=t.label,
                  before=before, after=changes)
    db.commit()
    db.refresh(t)
    return t


@router.delete("/{template_id}", status_code=204, summary="답변 문구 삭제 (관리자)")
def delete_template(template_id: int, request: Request, admin: AdminOnly, db: DB):
    t = _get(db, template_id)
    add_audit(db, request, "template_delete", admin, "reply_template", t.id, label=t.label, text=t.text)
    db.delete(t)
    db.commit()
