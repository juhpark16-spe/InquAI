"""문의 상세 화면에 함께 보여 줄 업무 정보: 주문 정보, 같은 고객의 다른 문의, 근거 FAQ 제목, 처리 이력.

상담원이 다른 화면을 오가지 않고 한 화면에서 판단·처리할 수 있게 모읍니다.
"""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database.models import AdminAuditLog, AdminUser, Customer, Faq, Inquiry, Order, Response, as_utc, utcnow

CANCELLABLE = ("결제 완료", "상품 준비 중")   # 출고 전 (docs/shop_policy.md 2장)
RETURN_DAYS, DEFECT_RETURN_DAYS = 7, 30      # 단순 변심 / 불량·오배송 (4장)
HISTORY_LIMIT = 5


def order_card(db: Session, inquiry: Inquiry) -> dict | None:
    """주문번호가 있으면 주문 정보와 정책상 가능한 처리(취소·반품 기한)를 계산해 돌려줍니다."""
    if not inquiry.order_number:
        return None
    row = db.execute(select(Order, Customer).join(Customer)
                     .where(Order.order_number == inquiry.order_number)).first()
    if row is None:
        return {"order_number": inquiry.order_number, "found": False}
    order, customer = row
    return _card(order, customer, inquiry.customer_email)


def email_orders(db: Session, inquiry: Inquiry) -> list[dict]:
    """주문번호를 적지 않았어도 문의 이메일과 같은 이메일로 주문한 내역 (최근 5건, 위 주문은 제외).

    문의 이메일은 본인 인증을 거치지 않아 남의 이메일일 수 있으므로, 화면에서 '본인 확인 필요'를 함께 보여 줍니다.
    관리자 화면에만 보이고 고객에게는 나가지 않습니다.
    """
    stmt = (select(Order, Customer).join(Customer)
            .where(func.lower(Customer.email) == inquiry.customer_email.lower()))
    if inquiry.order_number:
        stmt = stmt.where(Order.order_number != inquiry.order_number)
    rows = db.execute(stmt.order_by(Order.ordered_at.desc()).limit(HISTORY_LIMIT)).all()
    return [_card(o, c, inquiry.customer_email) for o, c in rows]


def _card(order: Order, customer: Customer, inquiry_email: str) -> dict:
    delivered = as_utc(order.delivered_at)
    now = utcnow()
    return_until = delivered + timedelta(days=RETURN_DAYS) if delivered else None
    return {
        "found": True,
        "order_number": order.order_number,
        "email_match": customer.email.lower() == inquiry_email.lower(),  # 다르면 본인 주문이 아닐 수 있음
        "orderer": customer.name,
        "product_name": order.product_name,
        "amount": order.amount,
        "order_status": order.order_status,
        "shipping_status": order.shipping_status,
        "tracking_number": order.tracking_number,
        "ordered_at": as_utc(order.ordered_at),
        "delivered_at": delivered,
        "cancellable": order.order_status in CANCELLABLE,
        "return_until": return_until,
        "returnable": bool(return_until and now <= return_until),
        "defect_return_until": delivered + timedelta(days=DEFECT_RETURN_DAYS) if delivered else None,
    }


def customer_history(db: Session, inquiry: Inquiry, user: AdminUser) -> list[dict]:
    """같은 이메일의 다른 문의 (최근 5건). 상담원은 자신에게 배정된 문의만."""
    stmt = select(Inquiry).where(Inquiry.customer_email == inquiry.customer_email, Inquiry.id != inquiry.id)
    if user.role != "admin":
        stmt = stmt.where(Inquiry.assigned_to == user.id)
    rows = db.scalars(stmt.order_by(Inquiry.created_at.desc()).limit(HISTORY_LIMIT)).all()
    return [{"id": i.id, "inquiry_number": i.inquiry_number, "title": i.title, "status": i.status,
             "created_at": i.created_at} for i in rows]


def mask_phone(phone: str | None) -> str | None:
    """010-1234-5678 → 010-****-5678 (상담원 화면에서도 가운데는 가림)"""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    return f"{digits[:3]}-****-{digits[-4:]}" if len(digits) >= 10 else "****"


def customer_profile(db: Session, inquiry: Inquiry) -> dict:
    """고객 카드: 쇼핑몰 회원 여부·전화번호(가림)·주문 수·문의 수·불만 신호 (같은 이메일 기준).

    불만 신호 = 이전 답변에 '도움 안 됨'(👎)을 준 횟수, 부정 감정 문의 수 → 응대에 더 신경 쓸 고객을 미리 알아봄
    """
    email = inquiry.customer_email.lower()
    customer = db.scalar(select(Customer).where(func.lower(Customer.email) == email))
    inquiries = db.scalars(select(Inquiry).where(func.lower(Inquiry.customer_email) == email)).all()
    ids = [i.id for i in inquiries]
    negative_ratings = db.scalar(select(func.count()).select_from(Response)
                                 .where(Response.inquiry_id.in_(ids), Response.rating == -1)) if ids else 0
    negative = sum(1 for i in inquiries if i.analysis and i.analysis.sentiment == "부정")
    return {
        "member": bool(customer and customer.password_hash),
        "phone": mask_phone(customer.phone) if customer else None,
        "orders": len(customer.orders) if customer else 0,
        "inquiries": len(inquiries),
        "negative_inquiries": negative,
        "negative_ratings": negative_ratings or 0,
    }


def faq_titles(db: Session, inquiry: Inquiry) -> dict[str, str]:
    """답변 근거·검색된 FAQ 번호 → 질문 (화면에서 번호 대신 내용을 보여 주려고)"""
    codes = set()
    for r in inquiry.responses:
        codes.update(r.used_faq_ids or [])
    for log in inquiry.agent_logs:
        codes.update(log.used_faq_ids or [])
        codes.update(c for c, _ in (log.retrieved_faqs or []))
    if not codes:
        return {}
    return {f.code: f.question for f in db.scalars(select(Faq).where(Faq.code.in_(codes)))}


def history(db: Session, inquiry: Inquiry) -> list[dict]:
    """처리 이력: 접수 → AI 판단 → 자동 배정·답변 발송 → 사람의 배정·상태 변경 (시간순)"""
    events = [{"at": inquiry.created_at, "actor": "고객", "text": "문의 접수", "kind": "received"}]
    events += [{"at": m.created_at, "actor": "고객", "text": "추가 문의", "kind": "followup"} for m in inquiry.messages]
    for log in inquiry.agent_logs:
        tool = f" · {log.selected_tool}" if log.selected_tool else ""
        fail = " (실패)" if log.tool_success is False else ""
        events.append({"at": log.created_at, "actor": "AI",
                       "text": f"{log.decision} 판단 ({log.decided_by}){tool}{fail}"
                               + ((" · 초안 작성 실패" if log.error.startswith("초안 작성 실패") else " · 오류로 상담원 검토")
                                  if log.error else ""), "kind": "ai"})
    names = {u.id: u.display_name for u in db.scalars(select(AdminUser))}


    logs = db.scalars(select(AdminAuditLog).where(AdminAuditLog.target_type == "inquiry",
                                                  AdminAuditLog.target_id == inquiry.id)).all()
    for a in logs:
        if a.action == "response_approve":  # 발송은 위 답변 기록에서 이미 보여 줌
            continue
        d = a.detail or {}
        kind = {"auto_assign": "assign", "assign": "assign", "status_change": "status"}.get(a.action, "draft")
        actor = names.get(a.admin_id, "시스템") if a.admin_id else "시스템"
        if a.action == "auto_assign":
            text = f"자동 배정 → {names.get(d.get('assigned_to'), '?')} ({d.get('rule', '')})"
        elif a.action == "assign":
            before, after = (d.get("before") or {}), (d.get("after") or {})
            text = f"배정 변경: {names.get(before.get('assigned_to'), '미배정')} → {names.get(after.get('assigned_to'), '미배정')}"
            if before.get("status") != after.get("status"):
                text += f" · 상태 {before.get('status')} → {after.get('status')}"
        elif a.action == "status_change":
            text = f"상태 변경: {d.get('before')} → {d.get('after')}"
        elif a.action == "response_create":
            text = "답변 작성"
        elif a.action == "response_edit":
            text = "답변 초안 수정"
        elif a.action == "label_correct":
            names = {"category": "유형", "sentiment": "감정", "route": "처리 경로", "urgency": "긴급도"}
            parts = [f"{names[f]} {b} → {c}" for f, (b, c) in {**d.get("changes", {}), **d.get("rule", {})}.items()]
            text, kind = "분류 수정: " + " · ".join(parts), "correct"
        elif a.action == "draft_generate":
            text = "AI 초안 다시 만들기" if d.get("replaced") else "AI 초안 만들기"
            if d.get("instruction"):
                text += f" (요청: {d['instruction']})"
        elif a.action in ("ticket_approve", "ticket_reject"):
            result = "승인" if a.action == "ticket_approve" else "반려"
            text = f"티켓 #{d.get('ticket_id')} {d.get('ticket_type')} {result}"
            if d.get("order"):
                text += f" · 주문 {d['order']['before']} → {d['order']['after']}"
            if d.get("memo"):
                text += f" ({d['memo']})"
            kind = "ticket"
        else:
            text = a.action
        events.append({"at": a.created_at, "actor": actor, "text": text, "kind": kind})

    # 답변 발송은 작업 기록 뒤에 넣음: 같은 시각이면(작성 → 발송을 한 번에) 작성이 먼저 보이도록 (정렬은 순서 유지)
    for r in inquiry.responses:
        if r.status == "발송":
            if r.approved_by is None:
                who, text = "AI", "자동 답변 발송"
            else:
                who = names.get(r.approved_by, "상담원")
                text = {"llm": "AI 초안 수정 후 발송" if r.is_edited else "AI 초안 그대로 발송"}.get(
                    r.generated_by, "직접 작성한 답변 발송")
            events.append({"at": r.approved_at or r.created_at, "actor": who, "text": text, "kind": "sent"})
    return sorted(events, key=lambda e: as_utc(e["at"]))
