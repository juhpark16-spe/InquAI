"""AI 답변 초안: 상담원이 검토할 문의(검토 대기·담당자 처리)에 답변 초안을 씁니다 (3주차).

쓰는 곳
    1. 문의 접수 때: 에이전트가 '답변 초안'으로 판단하면 바로 초안을 만들어 둠 (pipeline.run_agent)
    2. 문의 상세의 [AI 초안 만들기] 버튼: 담당자 연결 문의나 추가 문의에도 상담원이 원할 때 (POST /api/inquiries/{id}/draft)

근거로 넘기는 것: 검색된 FAQ(KURE) + 본인 확인된 주문 정보 + 티켓(처리 기록) + 대화(처음 문의·추가 문의·보낸 답변).
고객 이름·이메일은 넘기지 않습니다. 모르는 내용은 [확인 필요: …]로 남겨 상담원이 채우게 합니다.
"""

import re
import time
from dataclasses import dataclass, field
from datetime import timedelta, timezone

from langsmith import traceable
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.ai.prompts import DRAFT_PROMPT, DRAFT_SCHEMA, customer_text, find_promises
from backend.database.models import AdminAuditLog, Attachment, CustomerMessage, Inquiry, Response, Ticket, as_utc
from backend.services.inquiry_context import order_card

KST = timezone(timedelta(hours=9))
MAX_LEN = 4000
CHECK_MARK = "[확인 필요"
# 답변에 FAQ 번호가 섞여 나오면 지움: "(F27)", "[F05, F06]", "(FAQ F27)"
FAQ_REF = re.compile(r"\s?[(\[](?:FAQ\s*)?F\d{2}(?:\s*[,·/]\s*F\d{2})*[)\]]")


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
    if card["return_until"]:
        lines.append(f"단순 변심 반품 기한: {_kst(card['return_until'])}까지 ({'가능' if card['returnable'] else '지남'}), "
                     f"불량·오배송 반품 기한: {_kst(card['defect_return_until'])}까지")
    return "\n".join(lines)


def build_input(db: Session, inquiry: Inquiry, faqs: list[dict], analysis: dict | None) -> str:
    """LLM에 넘길 글. 고객 이름·이메일은 넣지 않음"""
    parts = []
    if analysis:
        parts.append(f"[분석] 유형: {analysis['category']}, 감정: {analysis['sentiment']}, 긴급도: {analysis['urgency']}")
    parts.append("[주문 정보]\n" + _order_text(order_card(db, inquiry)))
    photos = db.scalar(select(func.count()).select_from(Attachment).where(Attachment.inquiry_id == inquiry.id))
    parts.append(f"[첨부 사진] {photos}장 (너는 사진을 볼 수 없음)" if photos else "[첨부 사진] 없음")
    tickets = db.scalars(select(Ticket).where(Ticket.inquiry_id == inquiry.id).order_by(Ticket.id)).all()
    # 상담원의 바로 처리(배송지·옵션 변경, 부분 취소, 중복 승인 취소, 보상, 반품 접수)도 처리 기록으로 → 초안에 결과를 안내
    actions = db.scalars(select(AdminAuditLog).where(AdminAuditLog.target_type == "inquiry", AdminAuditLog.target_id == inquiry.id,
                                                     AdminAuditLog.action == "order_action").order_by(AdminAuditLog.id)).all()
    lines = [f"티켓 #{t.id} {t.ticket_type} {t.status}" + (f" (상담원 메모: {t.memo})" if t.memo else "") for t in tickets]
    lines += [f"상담원 처리 완료: {(a.detail or {}).get('summary', '')}" for a in actions]
    if inquiry.recheck_note:  # "확인 후 다시 안내드리겠습니다"를 이미 보냈고, 이번 답변이 그 확인 결과 안내
        lines.append(f"다시 안내하기로 한 내용: {inquiry.recheck_note} (확인 결과는 상담원이 채움)")
    parts.append("[처리 기록]\n" + ("\n".join(lines) or "없음"))
    parts.append("[FAQ]\n" + ("\n".join(f"[{f['id']}] Q: {f['question']}\nA: {f['answer']}" for f in faqs) or "관련 FAQ 없음"))

    messages = db.scalars(select(CustomerMessage).where(CustomerMessage.inquiry_id == inquiry.id)
                          .order_by(CustomerMessage.id)).all()
    sent = db.scalars(select(Response).where(Response.inquiry_id == inquiry.id, Response.status == "발송")
                      .order_by(Response.id)).all()
    talk = [(as_utc(inquiry.created_at), "고객 (처음 문의)", customer_text(f"제목: {inquiry.title}\n{inquiry.content}"))]
    talk += [(as_utc(m.created_at), "고객 (추가 문의)", customer_text(m.content)) for m in messages]
    talk += [(as_utc(r.approved_at or r.created_at), "고객센터 (보낸 답변)", r.final_text or r.draft_text) for r in sent]
    talk.sort(key=lambda t: t[0])
    parts.append("[대화] (시간순, 마지막 고객 글에 답할 것)\n" + "\n\n".join(f"{who} {_kst(at)}\n{text}" for at, who, text in talk))
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
    faqs = faq_search.search(search_query(db, inquiry), 3) if faq_search else []

    user_input = build_input(db, inquiry, faqs, analysis)
    if instruction and instruction.strip():
        user_input += f"\n\n[상담원 요청]\n{instruction.strip()[:200]}"
    data, usage = llm.json(DRAFT_PROMPT, user_input, DRAFT_SCHEMA, "draft", timeout=timeout)
    answer = FAQ_REF.sub("", data["answer"]).strip()[:MAX_LEN]
    known = {f["id"] for f in faqs}
    checks = [c.strip() for c in data["check_points"] if c.strip()][:10]
    # 안전장치: 지급·승인을 확정하는 말이 있으면 상담원이 꼭 보도록 확인할 것에 올림 (프롬프트를 어겨도 걸러지게)
    checks += [f"지급·승인을 확정하는 표현이 있습니다: '{p}' (사실인지 확인 후 고치세요)" for p in find_promises(answer)]
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
