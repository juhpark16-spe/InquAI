"""문의 상세 화면에 함께 보여 줄 업무 정보: 주문 정보, 같은 고객의 다른 문의, 근거 FAQ 제목, 처리 이력.

상담원이 다른 화면을 오가지 않고 한 화면에서 판단·처리할 수 있게 모읍니다.
"""

import re
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.database.models import (AdminAuditLog, AdminUser, Coupon, Customer, Faq, Inquiry, Notification, Order,
                                     PointHistory, Response, Ticket, as_utc, utcnow)
from backend.services import inventory
from backend.services.order_actions import duplicates

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
    card = order_detail(order, customer, inquiry.customer_email)
    # 같은 주문으로 들어온 다른 문의: 같은 일을 두 번 처리하거나 서로 다르게 안내하지 않게
    others = db.scalars(select(Inquiry).where(Inquiry.order_number == order.order_number, Inquiry.id != inquiry.id)
                        .order_by(Inquiry.created_at.desc())).all()
    card["related_inquiries"] = [{"id": i.id, "inquiry_number": i.inquiry_number, "title": i.title, "status": i.status,
                                  "created_at": i.created_at, "assigned_to": i.assigned_to} for i in others]
    return card


ORDER_IN_TEXT = re.compile(r"(?<!\d)(\d{8})(\s*-\s*|)(\d{4})(?!\d)")
SYSTEM_ORDER_NOTE = re.compile(r"\(주문번호 (추가|변경)[^)]*\)")


def _looks_like_order(date8: str, hyphen: str) -> bool:
    """하이픈이 있으면 주문번호로, 12자리가 붙어 있으면 앞 8자리가 날짜(20YYMMDD)일 때만 (12자리 운송장 번호와 구분)"""
    if hyphen.strip():
        return True
    month, day = int(date8[4:6]), int(date8[6:8])
    return date8.startswith("20") and 1 <= month <= 12 and 1 <= day <= 31


def order_resolves(db: Session, inquiry: Inquiry) -> bool:
    """문의의 주문번호가 실제 주문이고 주문자 이메일이 문의 이메일과 같은지 (아니면 고객·상담원이 고칠 수 있게)"""
    if not inquiry.order_number:
        return False
    row = db.execute(select(Customer.email).join(Order).where(Order.order_number == inquiry.order_number)).first()
    return row is not None and row[0].lower() == inquiry.customer_email.lower()


def relink_open_tickets(db: Session, inquiry: Inquiry) -> None:
    """문의의 주문번호가 바뀐 뒤: 아직 처리하지 않은 티켓(접수·처리 중)을 지금 주문번호의 주문으로 다시 연결 (없으면 연결을 뗌)"""
    order_id = db.scalar(select(Order.id).where(Order.order_number == inquiry.order_number)) if inquiry.order_number else None
    for t in db.scalars(select(Ticket).where(Ticket.inquiry_id == inquiry.id, Ticket.status.in_(("접수", "처리 중")))):
        t.order_id = order_id


def order_hints(db: Session, inquiry: Inquiry) -> list[dict]:
    """고객이 처음 글·추가 문의에 적은 주문번호 중 지금 문의에 붙은 번호와 다른 것 (상담원이 [이 번호로 확인]으로 바로 적용)"""
    texts = [inquiry.title, inquiry.content, *(m.content for m in inquiry.messages)]
    seen: list[str] = []
    for text in texts:
        for a, hyphen, b in ORDER_IN_TEXT.findall(SYSTEM_ORDER_NOTE.sub("", text or "")):
            if not _looks_like_order(a, hyphen):
                continue
            number = f"{a}-{b}"
            if number != inquiry.order_number and number not in seen:
                seen.append(number)
    out = []
    for number in seen[:3]:
        row = db.execute(select(Order, Customer).join(Customer).where(Order.order_number == number)).first()
        out.append({"order_number": number, "found": row is not None,
                    "email_match": bool(row) and row[1].email.lower() == inquiry.customer_email.lower(),
                    "product_name": row[0].product_name if row else None})
    return out


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
    return [order_detail(o, c, inquiry.customer_email) for o, c in rows]


def _payments(order: Order) -> tuple[list[dict], bool]:
    """결제·취소·환불 내역과 중복 결제 의심 여부 (정리되지 않은 중복 승인이 있으면, services/order_actions.duplicates)"""
    rows = [{"kind": p.kind, "status": p.status, "method": p.method, "amount": p.amount, "approval_no": p.approval_no,
             "at": as_utc(p.at), "memo": p.memo} for p in order.payments]
    return rows, bool(duplicates(order))


def _option(product_name: str) -> str | None:
    """'와이드 데님 팬츠 (연청, 28)' → '연청, 28' (옵션이 상품명 괄호에 들어 있음)"""
    m = re.match(r"^.*?\(([^)]*)\)\s*$", product_name)
    return m.group(1) if m else None


def order_detail(order: Order, customer: Customer, inquiry_email: str) -> dict:
    delivered = as_utc(order.delivered_at)
    now = utcnow()
    return_until = delivered + timedelta(days=RETURN_DAYS) if delivered else None
    payments, duplicate = _payments(order)
    qty = order.quantity or 1
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
        # 상담에 필요한 상세 (결제·수량·배송 추적·반품 진행)
        "quantity": qty,
        "unit_price": order.amount // qty,
        "option": _option(order.product_name),
        "payment_method": order.payment_method,
        "paid_at": as_utc(order.paid_at),
        "payments": payments,
        "duplicate_payment": duplicate,
        "carrier": order.carrier,
        "shipment_events": [{"at": as_utc(e.at), "status": e.status, "location": e.location} for e in order.shipment_events],
        "shipping_address": order.shipping_address,
        "option_choices": inventory.choices(order),   # 옵션별 재고 (옵션 변경·교환 안내)
        "return_requested_at": as_utc(order.return_requested_at),
        "picked_up_at": as_utc(order.picked_up_at),
        "related_inquiries": [],
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
    points, coupons = points_and_coupons(db, customer)
    return {
        **points, "coupons": coupons,
        "customer_id": customer.id if customer else None,   # 고객 조회 화면으로 가는 링크 (주소에 이메일을 넣지 않게 번호로)
        "member": bool(customer and customer.password_hash),
        "phone": mask_phone(customer.phone) if customer else None,
        "orders": len(customer.orders) if customer else 0,
        "inquiries": len(inquiries),
        "negative_inquiries": negative,
        "negative_ratings": negative_ratings or 0,
    }


def points_and_coupons(db: Session, customer: Customer | None) -> tuple[dict, list[dict]]:
    """적립금 잔액·적립 예정·최근 내역(5건)과 쿠폰(사용 가능한 것 먼저)"""
    if customer is None:
        return {"points_balance": None, "points_pending": 0, "point_history": []}, []
    rows = db.scalars(select(PointHistory).where(PointHistory.customer_id == customer.id)
                      .order_by(PointHistory.at.desc())).all()
    now = utcnow()
    points = {
        "points_balance": sum(r.amount for r in rows if r.status == "완료"),
        "points_pending": sum(r.amount for r in rows if r.status == "예정"),
        "point_history": [{"at": as_utc(r.at), "amount": r.amount, "reason": r.reason, "status": r.status,
                           "order_number": r.order_number} for r in rows[:HISTORY_LIMIT]],
    }
    coupons = []
    for c in db.scalars(select(Coupon).where(Coupon.customer_id == customer.id)):
        state = "사용함" if c.used_at else "만료" if as_utc(c.expires_at) < now else "사용 가능"
        coupons.append({"name": c.name, "benefit": c.benefit, "min_amount": c.min_amount,
                        "expires_at": as_utc(c.expires_at), "used_at": as_utc(c.used_at), "state": state})
    coupons.sort(key=lambda c: (c["state"] != "사용 가능", c["expires_at"]))
    return points, coupons


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


# AI 처리 기록을 관리자가 읽는 말로 (화면 frontend/src/services/labels.ts 와 같은 이름)
TOOL_LABEL = {"FAQ 검색": "FAQ로 답변", "티켓 접수": "처리 요청 접수"}
BY_LABEL = {"LLM": "AI가 판단", "규칙": "규칙으로 바로"}


def _fail_reason(output: dict | None) -> str:
    """도구 결과의 message: '주문번호 없음 (상담원이 고객에게 확인)' → '주문번호 없음'"""
    message = (output or {}).get("message") or ""
    return re.sub(r"\s*\(.*\)\s*$", "", message) or "이유 기록 없음"


def history(db: Session, inquiry: Inquiry) -> list[dict]:
    """처리 이력: 접수 → AI 판단 → 자동 배정·답변 발송 → 사람의 배정·상태 변경 (시간순)"""
    events = [{"at": inquiry.created_at, "actor": "고객", "text": "문의 접수", "kind": "received"}]
    events += [{"at": m.created_at, "actor": "고객", "text": "추가 문의", "kind": "followup"} for m in inquiry.messages]
    for log in inquiry.agent_logs:
        tool = f" · {TOOL_LABEL.get(log.selected_tool, log.selected_tool)}" if log.selected_tool else ""
        fail = f" (미완료: {_fail_reason(log.tool_output)})" if log.tool_success is False else ""
        events.append({"at": log.created_at, "actor": "AI",
                       "text": f"{log.decision} 판단 ({BY_LABEL.get(log.decided_by, log.decided_by)}){tool}{fail}"
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
            text = f"상태 변경: {d.get('before')} → {d.get('after')}" + (f" (사유: {d['reason']})" if d.get("reason") else "")
        elif a.action == "response_create":
            text = "답변 작성"
        elif a.action == "response_edit":
            text = "답변 초안 수정"
        elif a.action == "label_correct":
            # (사람 이름 목록 names 를 덮어쓰지 않도록 다른 이름으로: 덮어쓰면 이후 줄의 담당자 이름이 모두 깨짐)
            fields = {"category": "유형", "sentiment": "감정", "route": "처리 경로", "urgency": "긴급도"}
            parts = [f"{fields[f]} {b} → {c}" for f, (b, c) in {**d.get("changes", {}), **d.get("rule", {})}.items()]
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
        elif a.action == "order_action":
            text, kind = f"바로 처리 · {d.get('summary', '')}", "ticket"
        elif a.action == "note_create":
            text = "상담원 공유 메모 남김"
        elif a.action == "order_number_change":
            text, kind = f"주문번호 {'지정' if not d.get('before') else '변경'}: {d.get('before') or '없음'} → {d.get('after') or '없음'}", "ticket"
        elif a.action == "recheck_set":
            text, kind = f"다시 안내 예정 · {d.get('summary', '')}", "recheck"
        elif a.action == "recheck_clear":
            text, kind = f"다시 안내 완료 · {d.get('summary', '')}", "recheck"
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

    # 고객 답변 알림 메일 (backend/services/notify.py)
    for n in db.scalars(select(Notification).where(Notification.inquiry_id == inquiry.id).order_by(Notification.id)):
        text = MAIL_TEXT.get(n.status, n.status).format(to=n.recipient)
        if n.status == "실패" and n.error:
            text += f" ({n.error})"
        events.append({"at": n.sent_at or n.created_at, "actor": "시스템", "text": text, "kind": "mail"})
    return sorted(events, key=lambda e: as_utc(e["at"]))


MAIL_TEXT = {"기록": "고객 알림 기록 (메일 발송 꺼짐)", "대기": "고객 알림 메일 보내는 중 → {to}",
             "발송": "고객 알림 메일 발송 → {to}", "실패": "고객 알림 메일 실패 → {to}",
             "건너뜀": "고객 알림 메일 건너뜀 (예시 주소 {to})"}
