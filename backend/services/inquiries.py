"""문의 등록 처리: 저장 → 분석 → 에이전트 → 결과 저장 (docs/api_spec.md 3장 "서버 처리 순서")."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.agents.pipeline import run_agent
from backend.database.models import AgentLog, AnalysisResult, Inquiry, Response, utcnow
from backend.schemas.inquiry import InquiryCreate

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

MESSAGE_ANSWERED = "문의 번호와 이메일로 처리 상태를 다시 확인하실 수 있습니다."
MESSAGE_RECEIVED = "문의가 접수되었습니다. 담당자가 확인 후 답변드리겠습니다."


def _next_inquiry_number(db: Session) -> str:
    """INQ-날짜(한국 시간)-그날 순번. 고객에게 보여 주는 번호라 내부 id 대신 씁니다."""
    prefix = f"INQ-{datetime.now(KST):%Y%m%d}-"
    last = db.scalar(select(func.max(Inquiry.inquiry_number)).where(Inquiry.inquiry_number.like(f"{prefix}%")))
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def _save_inquiry(db: Session, body: InquiryCreate) -> Inquiry:
    for _ in range(3):  # 동시에 들어와 번호가 겹치면 다시 발급
        inquiry = Inquiry(inquiry_number=_next_inquiry_number(db), **body.model_dump())
        db.add(inquiry)
        try:
            db.commit()
            return inquiry
        except IntegrityError:
            db.rollback()
    raise RuntimeError("문의 번호 발급 실패")


def register_inquiry(db: Session, body: InquiryCreate, analyzer, faq_search, llm, timeout: float) -> dict:
    # 1. 저장 (접수). 이후 단계가 실패해도 문의는 남음
    inquiry = _save_inquiry(db, body)

    # 2. 분석
    try:
        analysis = analyzer.analyze(inquiry.content)
    except Exception:  # noqa: BLE001
        logger.exception("문의 분석 실패: %s", inquiry.inquiry_number)
        inquiry.status = "검토 대기"
        db.commit()
        return _customer_response(inquiry, None)

    # 3. 에이전트
    result = run_agent(db, inquiry, analysis, faq_search, llm, timeout)

    # 4. 결과 저장
    db.add(AnalysisResult(
        inquiry_id=inquiry.id, decision=result.decision, decided_by=result.decided_by,
        decision_reason=result.reason, **{k: analysis[k] for k in (
            "category", "confidence", "sentiment", "sentiment_confidence", "urgency", "route", "scores",
            "model_version")},
    ))
    sent = result.decision == "자동 답변"
    if result.answer:
        db.add(Response(inquiry_id=inquiry.id, draft_text=result.answer, generated_by="llm",
                        used_faq_ids=result.used_faq_ids, grounded=result.grounded,
                        status="발송" if sent else "초안", approved_at=utcnow() if sent else None))
    db.add(AgentLog(
        inquiry_id=inquiry.id, category=analysis["category"], confidence=analysis["confidence"],
        decision=result.decision, decided_by=result.decided_by, selected_tool=result.selected_tool,
        tool_success=result.tool_success, tool_output=result.tool_output, retrieved_faqs=result.retrieved_faqs,
        used_faq_ids=result.used_faq_ids, reason=result.reason, response_text=result.answer,
        llm_model=result.llm_model, tokens=result.tokens, latency_ms=result.latency_ms, error=result.error,
    ))
    inquiry.status = result.status
    db.commit()
    return _customer_response(inquiry, result.answer if sent else None)


def _customer_response(inquiry: Inquiry, answer: str | None) -> dict:
    """고객에게는 분석 결과·판단 이유를 보여 주지 않습니다."""
    return {"inquiry_number": inquiry.inquiry_number, "status": inquiry.status, "answer": answer,
            "message": MESSAGE_ANSWERED if answer else MESSAGE_RECEIVED}


def find_public_inquiry(db: Session, inquiry_number: str, email: str) -> dict | None:
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == inquiry_number,
                                              Inquiry.customer_email == email))
    if inquiry is None:
        return None
    sent = [r for r in inquiry.responses if r.status == "발송"]  # 초안은 고객에게 보이지 않음
    last = sent[-1] if sent else None
    return {"inquiry_number": inquiry.inquiry_number, "title": inquiry.title, "content": inquiry.content,
            "status": inquiry.status, "answer": (last.final_text or last.draft_text) if last else None,
            "created_at": inquiry.created_at, "answered_at": last.approved_at if last else None}
