"""문의 등록 처리: 저장 → 분석 → 에이전트 → 결과 저장 (docs/api_spec.md 3장 "서버 처리 순서")."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.agents.pipeline import needs_draft, run_agent
from backend.core.security import hash_password, verify_password
from backend.services import notify, uploads
from backend.services.assignment import auto_assign
from backend.core.errors import AppError
from backend.database.models import AgentLog, AnalysisResult, CustomerMessage, Inquiry, Response, utcnow
from backend.schemas.inquiry import InquiryCreate

logger = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

MESSAGE_ANSWERED = "이메일과 문의할 때 정한 비밀번호로 처리 상태를 다시 확인하실 수 있습니다."
MESSAGE_RECEIVED = ("문의가 접수되었습니다. 담당자가 확인 후 영업일 기준 1일 이내에 답변드리며, "
                    "답변이 등록되면 이메일로 알려 드립니다.")


def _next_inquiry_number(db: Session) -> str:
    """INQ-날짜(한국 시간)-그날 순번. 고객에게 보여 주는 번호라 내부 id 대신 씁니다."""
    prefix = f"INQ-{datetime.now(KST):%Y%m%d}-"
    last = db.scalar(select(func.max(Inquiry.inquiry_number)).where(Inquiry.inquiry_number.like(f"{prefix}%")))
    seq = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{seq:04d}"


def _save_inquiry(db: Session, body: InquiryCreate) -> Inquiry:
    fields = body.model_dump(exclude={"password", "privacy_agreed", "attachment_tokens"})
    fields["lookup_password_hash"] = hash_password(body.password)  # 평문 비밀번호는 저장하지 않음
    fields["privacy_agreed_at"] = utcnow()
    for _ in range(3):  # 동시에 들어와 번호가 겹치면 다시 발급
        inquiry = Inquiry(inquiry_number=_next_inquiry_number(db), **fields)
        db.add(inquiry)
        try:
            db.flush()
            uploads.claim(db, body.attachment_tokens, inquiry.id)  # 사진이 잘못되면 문의도 저장하지 않음 (AppError)
            db.commit()
            return inquiry
        except IntegrityError:
            db.rollback()
        except Exception:
            db.rollback()
            raise
    raise RuntimeError("문의 번호 발급 실패")


def register_inquiry(db: Session, body: InquiryCreate, analyzer, faq_search, llm, timeout: float,
                     schedule_draft=None) -> dict:
    """schedule_draft(inquiry_id): 답변 초안을 고객 응답 뒤에 쓰도록 맡길 함수 (API의 BackgroundTasks)"""
    # 1. 저장 (접수). 이후 단계가 실패해도 문의는 남음
    inquiry = _save_inquiry(db, body)

    # 2. 분석
    try:
        analysis = analyzer.analyze(inquiry.content)
    except Exception:  # noqa: BLE001
        logger.exception("문의 분석 실패: %s", inquiry.inquiry_number)
        inquiry.status = "검토 대기"
        _try_auto_assign(db, inquiry, None)  # 유형을 모르니 '전체 담당' 상담원에게
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
                        check_points=result.check_points or None,
                        status="발송" if sent else "초안", approved_at=utcnow() if sent else None))
    db.add(AgentLog(
        inquiry_id=inquiry.id, category=analysis["category"], confidence=analysis["confidence"],
        decision=result.decision, decided_by=result.decided_by, selected_tool=result.selected_tool,
        tool_success=result.tool_success, tool_output=result.tool_output, retrieved_faqs=result.retrieved_faqs,
        used_faq_ids=result.used_faq_ids, reason=result.reason, response_text=result.answer,
        llm_model=result.llm_model, tokens=result.tokens, latency_ms=result.latency_ms, error=result.error,
        steps=result.steps or None, trace_url=result.trace_url,
    ))
    inquiry.status = result.status
    # 5. 사람이 볼 문의(검토 대기·담당자 처리)는 담당 유형이 맞는 상담원에게 자동 배정
    _try_auto_assign(db, inquiry, analysis["category"])
    if sent:
        notify.answer_registered(db, inquiry)  # 자동 답변도 고객에게 알림 (시연용 기록)
    db.commit()
    # 6. 답변 초안: 고객은 기다리지 않게 응답 뒤에 씀 (backend/services/drafts.py)
    if needs_draft(result) and schedule_draft is not None:
        schedule_draft(inquiry.id)
    return _customer_response(inquiry, result.answer if sent else None)


def _try_auto_assign(db: Session, inquiry: Inquiry, category: str | None) -> None:
    try:
        with db.begin_nested():  # 배정이 실패해도 문의·분석 결과는 저장되도록
            auto_assign(db, inquiry, category)
    except Exception:  # noqa: BLE001
        logger.exception("자동 배정 실패: %s", inquiry.inquiry_number)


def _customer_response(inquiry: Inquiry, answer: str | None) -> dict:
    """고객에게는 분석 결과·판단 이유를 보여 주지 않습니다."""
    return {"inquiry_number": inquiry.inquiry_number, "status": inquiry.status, "answer": answer,
            "message": MESSAGE_ANSWERED if answer else MESSAGE_RECEIVED}


LOOKUP_LIMIT = 30  # 한 이메일에서 비밀번호를 확인해 볼 최근 문의 수 (Argon2 확인 1번에 수십 ms)


def find_public_inquiries(db: Session, email: str, password: str) -> list[dict]:
    """이메일이 같고 그 문의를 쓸 때 정한 비밀번호가 맞는 문의만 돌려줍니다 (최신순).

    같은 이메일이라도 비밀번호가 다른 문의는 보이지 않습니다. 그래서 남이 내 이메일로 문의를 남겨도
    그 사람은 자기 문의만 보고, 내 문의는 볼 수 없습니다.
    """
    return [_public(i) for i in _owned(db, email, password)]


def find_owned_inquiry(db: Session, email: str, password: str, inquiry_number: str) -> Inquiry | None:
    """추가 문의·답변 평가 전에 본인 문의인지 확인 (이메일 + 비밀번호 + 문의 번호)"""
    return next((i for i in _owned(db, email, password) if i.inquiry_number == inquiry_number), None)


def _owned(db: Session, email: str, password: str) -> list[Inquiry]:
    candidates = db.scalars(select(Inquiry).where(Inquiry.customer_email == email)
                            .order_by(Inquiry.created_at.desc(), Inquiry.id.desc()).limit(LOOKUP_LIMIT)).all()
    if not candidates:
        verify_password(password, None)  # 이메일이 없어도 같은 시간이 걸리게 (이메일 존재 여부 숨김)
        return []
    return [i for i in candidates if i.lookup_password_hash and verify_password(password, i.lookup_password_hash)]


def _public(inquiry: Inquiry) -> dict:
    sent = [r for r in inquiry.responses if r.status == "발송"]  # 초안은 고객에게 보이지 않음
    last = sent[-1] if sent else None
    # 대화형 화면용: 보낸 답변 전부 (시간순). 상담원 이름은 고객에게 알리지 않고 "상담원"으로만 표시
    answers = [{"id": r.id, "text": r.final_text or r.draft_text, "answered_at": r.approved_at or r.created_at,
                "by": "AI 상담원" if r.approved_by is None else "상담원", "rating": r.rating} for r in sent]
    return {"inquiry_number": inquiry.inquiry_number, "title": inquiry.title, "content": inquiry.content,
            "status": inquiry.status, "answer": (last.final_text or last.draft_text) if last else None,
            "created_at": inquiry.created_at, "answered_at": last.approved_at if last else None,
            "answers": answers,
            "messages": [{"id": m.id, "text": m.content, "at": m.created_at} for m in inquiry.messages],
            "attachment_count": len(inquiry.attachments),
            # 본인 확인을 통과한 응답에만 넣는 30분짜리 사진 주소 (처음 문의 사진은 message_id 없음)
            "attachments": [{"url": uploads.public_url(a), "filename": a.filename, "message_id": a.message_id}
                            for a in inquiry.attachments],
            "can_follow_up": len(inquiry.messages) < FOLLOW_UP_LIMIT}


FOLLOW_UP_LIMIT = 10  # 문의 1건에 추가 문의 최대 개수 (끝없는 대화 방지, 넘으면 새 문의로)
REOPEN_FROM = ("자동 처리", "완료")


def add_follow_up(db: Session, inquiry: Inquiry, content: str, tokens: list[str]) -> CustomerMessage:
    """고객 추가 문의: 저장 → 사진 연결 → 끝난 문의면 다시 열어 상담원에게 (AI 재분석은 하지 않음)"""
    if len(inquiry.messages) >= FOLLOW_UP_LIMIT:
        raise AppError(400, "이 문의에는 더 이상 추가 문의를 남길 수 없습니다. 새 문의로 남겨 주세요.", "TOO_MANY_MESSAGES")
    msg = CustomerMessage(inquiry_id=inquiry.id, content=content)
    db.add(msg)
    db.flush()
    uploads.claim(db, tokens, inquiry.id, message_id=msg.id)
    if inquiry.status in REOPEN_FROM or inquiry.status == "접수":
        inquiry.status = "담당자 처리"  # 사람이 이어서 봐야 함
    if inquiry.assigned_to is None:
        _try_auto_assign(db, inquiry, inquiry.analysis.category if inquiry.analysis else None)
    db.commit()
    return msg


def rate_answer(db: Session, inquiry: Inquiry, response_id: int, helpful: bool) -> Response:
    response = next((r for r in inquiry.responses if r.id == response_id and r.status == "발송"), None)
    if response is None:
        raise AppError(404, "답변을 찾을 수 없습니다.", "NOT_FOUND")
    response.rating, response.rated_at = (1 if helpful else -1), utcnow()  # 다시 누르면 바꿀 수 있음
    db.commit()
    return response
