"""작업 기록(감사 로그) 조회: GET /api/audit-logs (관리자, docs/api_spec.md).

누가 · 언제 · 무엇을 했는지(로그인·로그인 실패·계정 변경·배정·답변 발송·FAQ·답변 문구 등)를 보여 줍니다.
기록은 각 API가 services/audit.py 로 남기며, 이 API는 읽기만 합니다 (고치거나 지울 수 없음).
비밀번호·토큰 같은 비밀값은 처음부터 기록하지 않습니다.
"""

from datetime import timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from backend.core.dependencies import DB, AdminOnly
from backend.core.errors import AppError
from backend.database.models import AdminAuditLog, AdminUser, Customer, Faq, Inquiry, ReplyTemplate, as_utc, utcnow

router = APIRouter(prefix="/audit-logs", tags=["작업 기록"])

# action → (화면 이름, 묶음)
ACTIONS: dict[str, tuple[str, str]] = {
    "login": ("로그인", "로그인·보안"), "logout": ("로그아웃", "로그인·보안"),
    "login_failed": ("로그인 실패", "로그인·보안"), "password_change": ("비밀번호 변경", "로그인·보안"),
    "user_create": ("계정 만들기", "계정"), "user_update": ("계정 수정", "계정"),
    "user_password_reset": ("임시 비밀번호 발급", "계정"),
    "auto_assign": ("자동 배정", "문의 처리"), "assign": ("배정 변경", "문의 처리"),
    "status_change": ("상태 변경", "문의 처리"), "note_create": ("상담원 공유 메모", "문의 처리"),
    "label_correct": ("분류 수정", "문의 처리"), "ticket_approve": ("티켓 승인", "문의 처리"),
    "ticket_reject": ("티켓 반려", "문의 처리"), "order_action": ("바로 처리", "문의 처리"),
    "order_number_change": ("주문번호 변경", "문의 처리"), "customer_view": ("고객 정보 조회", "문의 처리"),
    "recheck_set": ("다시 안내 예정", "답변"), "recheck_clear": ("다시 안내 완료", "답변"),
    "draft_generate": ("AI 초안 만들기", "답변"), "response_create": ("답변 작성", "답변"),
    "response_edit": ("초안 수정", "답변"), "response_approve": ("답변 발송", "답변"),
    "faq_create": ("FAQ 추가", "설정"), "faq_update": ("FAQ 수정", "설정"), "faq_deactivate": ("FAQ 숨김", "설정"),
    "template_create": ("답변 문구 추가", "설정"), "template_update": ("답변 문구 수정", "설정"),
    "template_delete": ("답변 문구 삭제", "설정"), "template_reorder": ("답변 문구 순서 변경", "설정"),
}
GROUPS = ["로그인·보안", "계정", "문의 처리", "답변", "설정"]
FAIL_REASONS = {"wrong_password": "비밀번호 틀림", "unknown_user": "없는 아이디", "locked": "잠긴 계정",
                "inactive": "비활성 계정"}


def _summary(a: AdminAuditLog, names: dict[int, str]) -> str:
    """기록 내용을 한 줄로 (사람이 읽는 말로)"""
    d = a.detail or {}
    name = lambda i: names.get(i, "미배정") if i else "미배정"  # noqa: E731
    if a.action == "login_failed":
        reason = FAIL_REASONS.get(d.get("reason"), d.get("reason") or "")
        return f"{reason} · 시도한 아이디 '{d['username']}'" if d.get("username") else reason
    if a.action in ("order_action", "recheck_set", "recheck_clear"):
        return d.get("summary", "")
    if a.action == "order_number_change":
        return f"{d.get('before') or '없음'} → {d.get('after') or '없음'}"
    if a.action == "auto_assign":
        return f"→ {name(d.get('assigned_to'))}" + (f" ({d['rule']})" if d.get("rule") else "")
    if a.action == "assign":
        before, after = d.get("before") or {}, d.get("after") or {}
        return f"{name(before.get('assigned_to'))} → {name(after.get('assigned_to'))}"
    if a.action == "status_change":
        return f"{d.get('before')} → {d.get('after')}" + (f" · {d['reason']}" if d.get("reason") else "")
    if a.action in ("user_update", "template_update"):
        after = d.get("after") or {}
        return ", ".join(f"{k}: {v}" for k, v in after.items() if k != "text") + (" · 문장 변경" if "text" in after else "")
    if a.action == "user_create":
        after = d.get("after") or {}
        return f"{after.get('username', '')} ({'관리자' if after.get('role') == 'admin' else '상담원'})"
    if a.action == "draft_generate" and d.get("instruction"):
        return f"요청: {d['instruction']}"
    if a.action == "response_approve":
        return "AI 초안 수정 후 발송" if d.get("is_edited") else ("AI 초안 그대로 발송" if d.get("generated_by") == "llm" else "")
    if a.action in ("ticket_approve", "ticket_reject"):
        order = d.get("order") or {}
        parts = [d.get("ticket_type"), d.get("memo"),
                 f"주문 {order['order_number']} {order.get('before')} → {order.get('after')}" if order.get("order_number") else None]
        return " · ".join(p for p in parts if p)
    if a.action.startswith("template_") and d.get("label"):
        return d["label"]
    if a.action.startswith("faq_") and d.get("code"):
        return d["code"]
    return ""


@router.get("", summary="작업 기록 (관리자)")
def list_audit_logs(
    _: AdminOnly,
    db: DB,
    group: str | None = Query(None, description=" · ".join(GROUPS)),
    actor: str | None = Query(None, description="계정 id, 또는 system(자동 처리) / unknown(없는 아이디로 로그인 시도)"),
    days: int = Query(7, ge=1, le=90),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100),
):
    stmt = select(AdminAuditLog).where(AdminAuditLog.created_at >= utcnow() - timedelta(days=days))
    if group:
        if group not in GROUPS:
            raise AppError(422, f"group 은 {', '.join(GROUPS)} 중 하나입니다.", "INVALID_PARAM")
        stmt = stmt.where(AdminAuditLog.action.in_([k for k, (_, g) in ACTIONS.items() if g == group]))
    if actor in ("system", "unknown"):
        stmt = stmt.where(AdminAuditLog.admin_id.is_(None))
        stmt = stmt.where(AdminAuditLog.action == "login_failed" if actor == "unknown" else AdminAuditLog.action != "login_failed")
    elif actor:
        if not actor.isdigit():
            raise AppError(422, "actor 는 계정 id, system, unknown 중 하나입니다.", "INVALID_PARAM")
        stmt = stmt.where(AdminAuditLog.admin_id == int(actor))

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    failed = db.scalar(select(func.count()).select_from(
        stmt.where(AdminAuditLog.action == "login_failed").subquery()))
    rows = db.scalars(stmt.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
                      .offset((page - 1) * size).limit(size)).all()

    names = {u.id: u.display_name for u in db.scalars(select(AdminUser))}
    ids = lambda t: {a.target_id for a in rows if a.target_type == t and a.target_id}  # noqa: E731
    inquiries = {i.id: i.inquiry_number for i in db.scalars(select(Inquiry).where(Inquiry.id.in_(ids("inquiry"))))}
    faqs = {f.id: f.code for f in db.scalars(select(Faq).where(Faq.id.in_(ids("faq"))))}
    customers = {c.id: c.name for c in db.scalars(select(Customer).where(Customer.id.in_(ids("customer"))))}
    templates = {t.id: t.label for t in db.scalars(select(ReplyTemplate).where(ReplyTemplate.id.in_(ids("reply_template"))))}

    def target(a: AdminAuditLog) -> dict | None:
        if not a.target_type or not a.target_id:
            return None
        label = {"inquiry": inquiries, "admin_user": names, "faq": faqs, "reply_template": templates,
                 "customer": customers}.get(a.target_type, {}).get(a.target_id)
        if label is None and a.target_type == "reply_template":
            label = (a.detail or {}).get("label")       # 지운 문구는 기록에 남긴 이름으로
        link = {"inquiry": f"/admin/inquiries/{a.target_id}", "admin_user": "/admin/users",
                "faq": "/admin/faqs", "reply_template": "/admin/templates", "customer": f"/admin/customers/{a.target_id}"}.get(a.target_type)
        return {"type": a.target_type, "id": a.target_id, "label": label or f"#{a.target_id}", "link": link}

    items = [{
        "id": a.id, "at": as_utc(a.created_at), "action": a.action,
        "label": ACTIONS.get(a.action, (a.action, "기타"))[0], "group": ACTIONS.get(a.action, ("", "기타"))[1],
        "actor": ({"id": a.admin_id, "name": names.get(a.admin_id, f"#{a.admin_id}")} if a.admin_id
                  else {"id": None, "name": "알 수 없음" if a.action == "login_failed" else "시스템"}),
        "target": target(a), "summary": _summary(a, names), "ip": (a.detail or {}).get("ip"),
    } for a in rows]
    return {"items": items, "total": total, "login_failed": failed, "page": page, "size": size,
            "groups": GROUPS, "range_days": days}
