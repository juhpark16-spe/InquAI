"""AI 답변 초안: 상담원이 검토할 문의(검토 대기·담당자 처리)에 답변 초안을 씁니다 (3주차).

쓰는 곳
    1. 문의 접수 때: 에이전트가 '답변 초안'으로 판단하면 바로 초안을 만들어 둠 (pipeline.run_agent)
    2. 문의 상세의 [AI 초안 만들기] 버튼: 담당자 연결 문의나 추가 문의에도 상담원이 원할 때 (POST /api/inquiries/{id}/draft)

근거로 넘기는 것: 검색된 FAQ(KURE) + 본인 확인된 주문 정보 + 티켓(처리 기록) + 대화(처음 문의·추가 문의·보낸 답변).
주문 정보에는 결제 수단별 환불 기간·최근 배송 기록·반품 회수 상태도, [정책]에는 상담원 '답변 문구' 중 정책 문구(회수·환불 일정 등)를
넣어 "언제·어디쯤"에 숫자로 답하게 함 (2026-11-26, 지침의 '결론 먼저' 규칙과 함께, docs/agent_eval.md).
대화에는 글마다 함께 온 사진 수와 [답변 상황](첫 답변인지)을 붙여, 고객이 추가 문의로 보낸 주문번호·사진을 AI가 알아보게 함.
첫 답변(아직 보낸 답변 없음)은 맨 앞에 '첫인사' 문구(관리자 '답변 문구'의 첫인사)를 꼭 붙임 (2026-11-24).
고객 이름·이메일은 넘기지 않습니다. 모르는 내용은 [확인 필요: …]로 남겨 상담원이 채우게 합니다.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from langsmith import traceable
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.prompts import DRAFT_PROMPT, DRAFT_SCHEMA, customer_text, find_promises
from backend.rag.category_boost import search_with_category
from backend.database.models import (AdminAuditLog, Attachment, CustomerMessage, Inquiry, ReplyTemplate, Response, Ticket,
                                     as_utc)
from backend.services import inventory, photo_evidence, refund_account
from backend.services.policy import refund_timing
from backend.services.inquiry_context import order_card
from backend.services.reply_templates import DEFAULTS as TEMPLATE_DEFAULTS

KST = timezone(timedelta(hours=9))
MAX_LEN = 4000
CHECK_MARK = "[확인 필요"
# 답변에 FAQ 번호가 섞여 나오면 지움: "(F27)", "[F05, F06]", "(FAQ F27)"
FAQ_REF = re.compile(r"\s?[(\[](?:FAQ\s*)?F\d{2}(?:\s*[,·/]\s*F\d{2})*[)\]]")
# AI가 스스로 쓴 인사 (첫 답변에는 정해진 첫인사를 붙이므로 겹치지 않게 지움): "안녕하세요(, 고객님)." + "…고객센터입니다."
# 인사말만 지움: "안녕하세요(,) (고객님|○○님)(.)" + 바로 뒤의 짧은 "…고객센터입니다." 문장. 같은 문장에 이어지는 사과·본론은 남김
# (예: "안녕하세요 고객님, 배송이 늦어져 죄송합니다." → "배송이 늦어져 죄송합니다.")
GREETING = re.compile(r"^\s*안녕하세요[,\s]*(?:[가-힣]{1,6}\s?님|고객님)?\s*[.!,]?\s*(?:[^.!?\n]{0,30}고객센터입니다[.!]?\s*)?")
DEFAULT_GREETING = dict(TEMPLATE_DEFAULTS)["첫인사"]


def greeting_text(db: Session) -> str:
    """관리자가 '답변 문구'에서 고친 첫인사 (숨겼거나 없으면 기본 문구)"""
    t = db.scalar(select(ReplyTemplate).where(ReplyTemplate.label == "첫인사", ReplyTemplate.is_active.is_(True))
                  .order_by(ReplyTemplate.sort_order, ReplyTemplate.id).limit(1))
    return t.text.strip() if t and t.text.strip() else DEFAULT_GREETING


def with_greeting(answer: str, greeting: str) -> str:
    """첫 답변: AI가 쓴 인사는 지우고 정해진 첫인사를 맨 앞에"""
    body = GREETING.sub("", answer, count=1).lstrip()
    return f"{greeting}\n\n{body}" if body else greeting


def is_first_answer(db: Session, inquiry: Inquiry) -> bool:
    """이 문의에 고객에게 보낸 답변이 아직 없음 (자동 답변 포함)"""
    return db.scalar(select(Response.id).where(Response.inquiry_id == inquiry.id, Response.status == "발송").limit(1)) is None


@dataclass
class DraftResult:
    answer: str
    used_faq_ids: list[str]
    grounded: bool
    check_points: list[str]
    retrieved_faqs: list = field(default_factory=list)   # [[FAQ 번호, 점수], ...]
    tokens: dict = field(default_factory=dict)
    latency_ms: int = 0
    llm_model: str | None = None


def _kst(dt) -> str:
    return as_utc(dt).astimezone(KST).strftime("%m/%d %H:%M")


def _won(n) -> str:
    return f"{n:,}원" if n is not None else "-"


def _order_text(card: dict | None) -> str:
    if card is None:
        return "주문번호 없음"
    if not card.get("found"):
        return f"주문번호 {card['order_number']}: 주문을 찾을 수 없음 (번호 확인 필요)"
    if not card["email_match"]:
        return f"주문번호 {card['order_number']}: 문의 이메일과 주문자 이메일이 다름 → 본인 확인 필요 (주문 내용을 알려 주지 말 것)"
    lines = [
        f"주문번호 {card['order_number']} · {card['product_name']} · {_won(card['amount'])}",
        f"주문 상태: {card['order_status']} / 배송: {card['shipping_status'] or '-'}"
        + (f" / 운송장 {card['tracking_number']}" if card["tracking_number"] else ""),
        f"주문일: {_kst(card['ordered_at'])}" + (f" / 배송 완료: {_kst(card['delivered_at'])}" if card["delivered_at"] else ""),
        f"출고 전 취소 가능: {'예' if card['cancellable'] else '아니요'}",
    ]
    if card.get("payment_method"):   # 결제 수단별 환불 기간: "언제 환불되나요"에 숫자로 답하게
        lines.append(f"결제: {card['payment_method']} · 환불(승인 취소) 반영 기간: {refund_timing(card['payment_method'])}")
    events = card.get("shipment_events") or []
    if events:   # 마지막 배송 기록: "지금 어디쯤인가요"에 실제 위치로 답하게
        e = events[-1]
        lines.append(f"최근 배송 기록: {_kst(e['at'])} {e['status']}" + (f" ({e['location']})" if e.get("location") else "")
                     + (f" · 택배사 {card['carrier']}" if card.get("carrier") else ""))
    if card.get("return_requested_at"):   # 반품 회수 접수 뒤: 수거 여부와 환불 예정 금액
        lines.append(f"반품 회수 접수: {_kst(card['return_requested_at'])}"
                     + (f" (사유: {card['return_reason']})" if card.get("return_reason") else "")
                     + (f" · 수거 완료 {_kst(card['picked_up_at'])}" if card.get("picked_up_at") else " · 아직 수거 전")
                     + (f" · 환불 예정 {_won(card['refund_preview'])}" if card.get("refund_preview") is not None else ""))
    if card.get("option_choices"):   # 같은 상품의 옵션별 재고: 옵션 변경·교환 문의에 재고를 근거로 안내
        lines.append("같은 상품 옵션 재고: " + " · ".join(inventory.describe(c) for c in card["option_choices"]))
    if card["return_until"]:
        lines.append(f"단순 변심 반품 기한: {_kst(card['return_until'])}까지 ({'가능' if card['returnable'] else '지남'}), "
                     f"불량·오배송 반품 기한: {_kst(card['defect_return_until'])}까지")
    return "\n".join(lines)


INTERNAL_TERMS = re.compile(r"처리 기록|티켓|FAQ")   # 고객 답변에 나오면 안 되는 내부 용어

TICKET_NAME = {"취소": "주문 취소", "교환": "교환", "환불": "반품(환불)"}   # 서버 값 '환불' = 반품 후 환불
NOT_POLICY = {"첫인사", "사과", "마무리"}   # 답변 문구 중 인사말 (정책 사실이 아니라 [정책]에서 뺌)


def policy_lines(db: Session) -> list[str]:
    """상담원 '답변 문구'(관리자 화면) 중 정책 사실이 담긴 문구(회수·환불 일정, 취소 완료, 파손 등) → 초안이 기간을 숫자로 쓰게.
    관리자가 문구를 고치면 AI 근거도 같이 바뀜"""
    rows = db.scalars(select(ReplyTemplate).where(ReplyTemplate.is_active.is_(True))
                      .order_by(ReplyTemplate.sort_order, ReplyTemplate.id)).all()
    items = [(t.label, t.text) for t in rows] or list(TEMPLATE_DEFAULTS)
    return [f"- {label}: {text.strip()}" for label, text in items if label not in NOT_POLICY and text.strip()]


def _ticket_line(t: Ticket) -> str:
    """[처리 기록]의 요청 한 줄을 AI가 오해하지 않게 풀어 씀.
    예전엔 '티켓 #18 환불 접수'만 넘겨서, 이 문의로 이미 반품이 접수된 줄 모르고 'FAQ대로 마이페이지에서 신청하라'고 안내함"""
    if t.ticket_type == "이관":
        return "상담원 확인 요청됨 (사람이 확인 중)"
    name = TICKET_NAME.get(t.ticket_type, t.ticket_type)
    memo = f" (상담원 메모: {t.memo})" if t.memo else ""
    if t.status == "접수":
        return (f"{name} 요청 접수됨: 이 문의로 이미 요청이 접수돼 있음 → 고객이 마이페이지 등에서 따로 다시 신청할 필요 없음. "
                f"상담원이 주문을 확인한 뒤 승인·처리 (아직 승인 전이라 처리됐다고 쓰지 말 것){memo}")
    if t.status == "승인":
        return f"{name} 요청 승인됨{memo}"
    return f"{name} 요청 반려됨{memo or ' (사유는 상담원이 채움)'}"


def build_input(db: Session, inquiry: Inquiry, faqs: list[dict], analysis: dict | None) -> str:
    """LLM에 넘길 글. 고객 이름·이메일은 넣지 않음"""
    parts = []
    if analysis:
        parts.append(f"[분석] 유형: {analysis['category']}, 감정: {analysis['sentiment']}, 긴급도: {analysis['urgency']}")
    parts.append("[주문 정보]\n" + _order_text(order_card(db, inquiry)))
    photos = db.scalars(select(Attachment).where(Attachment.inquiry_id == inquiry.id)).all()
    labels = ", ".join(a.label for a in photos if a.label)
    # 사과가 필요한 쇼핑몰 쪽 문제를 분명히 알려 줌 (파손 문의에 사과를 빠뜨리거나, '생각보다 작아요' 같은 고객 사정에 사과하지 않게)
    follow_text = " ".join(m.content for m in db.scalars(select(CustomerMessage).where(CustomerMessage.inquiry_id == inquiry.id)))
    if (any(a.label == "파손 부위" for a in photos) or inquiry.photo_request
            or photo_evidence.needs_photos(inquiry.title, f"{inquiry.content} {follow_text}")):
        parts.append("[쇼핑몰 쪽 문제] 파손·불량·오배송 문의 → 첫 문장에 짧게 사과할 것")
    if photos:
        parts.append(f"[첨부 사진] {len(photos)}장" + (f" ({labels})" if labels else "") + " (너는 사진을 볼 수 없음)")
    elif inquiry.photo_request:   # 파손 문의인데 고객이 사진을 나중에 보내기로 함 → 답변에서 사진을 먼저 요청
        parts.append("[첨부 사진] 없음 — 고객이 나중에 보내기로 함. 송장이 보이는 사진 1장과 파손 부위 사진 1장을 추가 문의로 보내 달라고 요청할 것")
    else:
        parts.append("[첨부 사진] 없음")
    tickets = db.scalars(select(Ticket).where(Ticket.inquiry_id == inquiry.id).order_by(Ticket.id)).all()
    # 상담원의 바로 처리(배송지·옵션 변경, 부분 취소, 중복 승인 취소, 보상, 반품 접수)도 처리 기록으로 → 초안에 결과를 안내
    actions = db.scalars(select(AdminAuditLog).where(AdminAuditLog.target_type == "inquiry", AdminAuditLog.target_id == inquiry.id,
                                                     AdminAuditLog.action == "order_action").order_by(AdminAuditLog.id)).all()
    lines = [_ticket_line(t) for t in tickets]
    lines += [f"상담원 처리 완료: {(a.detail or {}).get('summary', '')}" for a in actions]
    # 환불 계좌: 번호는 넘기지 않고 받았는지만 (계좌번호를 다시 묻거나 글로 적어 달라고 하지 않게)
    if inquiry.refund_account:
        lines.append("환불 계좌 받음 (무통장입금 환불용, 번호는 상담원만 확인 → 답변에 계좌번호를 쓰거나 다시 묻지 말 것)")
    elif refund_account.needed(db, inquiry):
        lines.append("환불 계좌 아직 없음 (무통장입금 주문): 계좌번호를 글로 적지 말고 문의 조회·내 쇼핑의 "
                     "[내용 보충 · 추가 문의] '환불 계좌' 칸에 입력해 달라고 안내할 것")
    if inquiry.recheck_note:  # "확인 후 다시 안내드리겠습니다"를 이미 보냈고, 이번 답변이 그 확인 결과 안내
        lines.append(f"다시 안내하기로 한 내용: {inquiry.recheck_note} (확인 결과는 상담원이 채움)")
    parts.append("[처리 기록]\n" + ("\n".join(lines) or "없음"))
    parts.append("[FAQ]\n" + ("\n".join(f"[{f['id']}] Q: {f['question']}\nA: {f['answer']}" for f in faqs) or "관련 FAQ 없음"))
    policy = policy_lines(db)
    if policy:
        parts.append("[정책] (상담원 답변 문구. 이 문의에 해당할 때만 근거로)\n" + "\n".join(policy))

    messages = db.scalars(select(CustomerMessage).where(CustomerMessage.inquiry_id == inquiry.id)
                          .order_by(CustomerMessage.id)).all()
    sent = db.scalars(select(Response).where(Response.inquiry_id == inquiry.id, Response.status == "발송")
                      .order_by(Response.id)).all()
    # 글마다 함께 온 사진 수 (처음 문의 = message_id 없음): 추가 문의로 사진을 보냈다는 걸 AI가 알게
    per_msg: dict[int | None, int] = {}
    for a in photos:
        per_msg[a.message_id] = per_msg.get(a.message_id, 0) + 1

    def who(label: str, key: int | None) -> str:
        return label + (f" [사진 {per_msg[key]}장 함께 보냄]" if per_msg.get(key) else "")

    talk = [(as_utc(inquiry.created_at), who("고객 (처음 문의)", None), customer_text(f"제목: {inquiry.title}\n{inquiry.content}"))]
    talk += [(as_utc(m.created_at), who("고객 (추가 문의)", m.id), customer_text(m.content)) for m in messages]
    talk += [(as_utc(r.approved_at or r.created_at), "고객센터 (보낸 답변)", r.final_text or r.draft_text) for r in sent]
    talk.sort(key=lambda t: t[0])
    if not sent:
        parts.append("[답변 상황] 첫 답변 (아직 보낸 답변 없음): 처음 문의의 요청 전체에 답하고, 추가 문의로 보낸 정보"
                     "(주문번호·사진 등)를 반영할 것. 인사말은 쓰지 말 것 (정해진 첫인사가 자동으로 붙음)")
    else:
        parts.append(f"[답변 상황] 이어지는 답변 (보낸 답변 {len(sent)}건): 가장 최근 고객 글에 답할 것. 인사는 생략")
    parts.append("[대화] (시간순)\n" + "\n\n".join(f"{w} {_kst(at)}\n{text}" for at, w, text in talk))
    return "\n\n".join(parts)


def search_query(db: Session, inquiry: Inquiry) -> str:
    """FAQ 검색 문장: 처음 문의 + 가장 최근 추가 문의 (추가 문의가 다른 내용일 수 있어서)"""
    last = db.scalar(select(CustomerMessage).where(CustomerMessage.inquiry_id == inquiry.id)
                     .order_by(CustomerMessage.id.desc()).limit(1))
    return f"{inquiry.title}\n{inquiry.content}" + (f"\n{last.content}" if last else "")


def _trace_inputs(inputs: dict) -> dict:
    """LangSmith에 남길 입력: DB 세션·문의 객체 대신 문의 번호만 (원문은 LLM 호출 기록에 가려져 남음)"""
    return {"inquiry_number": inputs["inquiry"].inquiry_number}


@traceable(name="답변 초안 작성", run_type="chain", process_inputs=_trace_inputs)
def generate_draft(db: Session, inquiry: Inquiry, faq_search, llm, timeout: float,
                   analysis: dict | None = None, instruction: str | None = None) -> DraftResult:
    """instruction: 상담원 요청 (예: "더 짧게"). 고객 글과 섞이지 않게 [상담원 요청]으로 따로 넘김"""
    """초안 1개를 만듭니다. LLM 오류·시간 초과는 예외로 올라갑니다 (부르는 쪽에서 처리)."""
    if llm is None:
        raise RuntimeError("LLM을 쓸 수 없습니다 (OPENAI_API_KEY 없음).")
    if timeout <= 1:
        raise TimeoutError("초안을 만들 시간이 부족합니다.")
    start = time.monotonic()
    if analysis is None and inquiry.analysis is not None:
        a = inquiry.analysis
        analysis = {"category": a.category, "sentiment": a.sentiment, "urgency": a.urgency}
    # 분류 결과로 FAQ 순서 보정 (backend/rag/category_boost.py): 넘겨받은 분석 → 저장된 분석 순으로 유형·확신도
    saved = inquiry.analysis
    category = (analysis or {}).get("category") or (saved.category if saved else None)
    confidence = (analysis or {}).get("confidence", saved.confidence if saved else None)
    faqs = search_with_category(faq_search, search_query(db, inquiry), category, confidence) if faq_search else []

    user_input = build_input(db, inquiry, faqs, analysis)
    if instruction and instruction.strip():
        user_input += f"\n\n[상담원 요청]\n{instruction.strip()[:200]}"
    data, usage = llm.json(DRAFT_PROMPT, user_input, DRAFT_SCHEMA, "draft", timeout=timeout)
    answer = FAQ_REF.sub("", data["answer"]).strip()
    if is_first_answer(db, inquiry):   # 고객에게 가는 첫 답변은 첫인사로 시작 (AI가 빠뜨려도)
        answer = with_greeting(answer, greeting_text(db))
    answer = answer[:MAX_LEN]
    known = {f["id"] for f in faqs}
    checks = [c.strip() for c in data["check_points"] if c.strip()][:10]
    # 안전장치: 지급·승인을 확정하는 말이 있으면 상담원이 꼭 보도록 확인할 것에 올림 (프롬프트를 어겨도 걸러지게)
    checks += [f"지급·승인을 확정하는 표현이 있습니다: '{p}' (사실인지 확인 후 고치세요)" for p in find_promises(answer)]
    # 안전장치: 내부 용어가 고객 글에 남았으면 상담원이 고치도록 (프롬프트를 어겨도 걸러지게)
    checks += [f"내부 용어가 들어 있습니다: '{w}' (고객이 알아듣는 말로 고치세요)" for w in sorted(set(INTERNAL_TERMS.findall(answer)))]   # 같은 단어는 한 번만
    return DraftResult(
        answer=answer,
        used_faq_ids=[i for i in data["used_faq_ids"] if i in known],   # 넘기지 않은 FAQ 번호는 버림
        grounded=bool(data["grounded"]) and CHECK_MARK not in answer and not checks,
        check_points=checks,
        retrieved_faqs=[[f["id"], round(f["score"], 3)] for f in faqs],
        tokens={"input": usage.get("input", 0), "output": usage.get("output", 0), "calls": 1},
        latency_ms=int((time.monotonic() - start) * 1000),
        llm_model=llm.label,
    )
