"""문의 등록 처리: 저장 → 분석 → 에이전트 → 결과 저장 (docs/api_spec.md 3장 "서버 처리 순서")."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from backend.agents.pipeline import needs_draft, run_agent
from backend.core.security import hash_password, verify_password
from backend.services import exchange_fee, notify, photo_evidence, refund_account, uploads
from backend.services.assignment import auto_assign
from backend.services.inquiry_context import order_resolves, relink_open_tickets
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
    photo_evidence.check(body.title, body.content, body.attachment_tokens, body.photo_labels, body.photos_later,
                         body.damage_report)   # 파손 문의: 송장·파손 부위 사진 또는 '지금은 사진이 없어요'
    fields = body.model_dump(exclude={"password", "privacy_agreed", "attachment_tokens", "photo_labels", "damage_report",
                                      "photos_later", "refund_account"})   # client_request_id 는 그대로 저장 (다시 눌렀는지 알아보려고)
    needs = photo_evidence.needs_photos(body.title, body.content, body.damage_report)
    # 두 칸(송장·파손 부위) 중 하나라도 비었는데 '지금은 사진이 없어요'면 → 나중에 받음 (한 장만 올린 경우도)
    missing = set(photo_evidence.LABELS) - set(body.photo_labels.values())
    fields["photo_request"] = photo_evidence.LATER if needs and body.photos_later and missing else None
    # 평문 비밀번호는 저장하지 않음. 로그인 고객은 비밀번호 없이 '내 문의'로 봄
    fields["lookup_password_hash"] = hash_password(body.password) if body.password else None
    fields["privacy_agreed_at"] = utcnow()
    for _ in range(3):  # 동시에 들어와 번호가 겹치면 다시 발급
        inquiry = Inquiry(inquiry_number=_next_inquiry_number(db), **fields)
        if body.refund_account:   # 무통장입금 주문 취소·반품: 환불 계좌는 글과 따로 (AI에 넘기지 않음)
            refund_account.save(inquiry, body.refund_account.bank, body.refund_account.holder, body.refund_account.number)
        db.add(inquiry)
        try:
            db.flush()
            for a in uploads.claim(db, body.attachment_tokens, inquiry.id):  # 사진이 잘못되면 문의도 저장하지 않음 (AppError)
                a.label = body.photo_labels.get(a.token)
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
    # 0. 같은 화면에서 다시 누른 등록(응답이 늦어 시간 초과 뒤 재시도): 이미 만든 문의를 그대로 돌려줌
    if body.client_request_id:
        same = db.scalar(select(Inquiry).where(Inquiry.client_request_id == body.client_request_id,
                                               Inquiry.customer_email == body.customer_email))
        if same is not None:
            sent = [r for r in same.responses if r.status == "발송"]
            return _customer_response(same, (sent[-1].final_text or sent[-1].draft_text) if sent else None)

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
    analysis = result.analysis or analysis   # 표기 재확인으로 유형이 바뀌었을 수 있음

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


def find_customer_inquiries(db: Session, email: str, limit: int = 50) -> list[Inquiry]:
    """쇼핑몰에 로그인한 고객의 문의 (이메일이 같은 문의 전부, 최신순). 로그인으로 본인 확인이 끝났으므로 조회 비밀번호는 보지 않음"""
    return db.scalars(select(Inquiry).where(Inquiry.customer_email == email)
                      .order_by(Inquiry.created_at.desc(), Inquiry.id.desc()).limit(limit)).all()


def public_view(inquiry: Inquiry) -> dict:
    return _public(inquiry)


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


# 답변 없이 종료한 사유 → 고객에게 보여 줄 말 (스팸·광고는 사유를 말하지 않음)
CLOSED_TEXT = {"중복 문의": "같은 내용의 다른 문의에서 안내드려요.", "고객 철회": "문의를 취소하셔서 종료했어요.",
               "전화로 안내": "전화로 안내드리고 종료했어요.", "스팸·광고": "상담원이 확인 후 종료했어요.",
               "기타": "상담원이 확인 후 종료했어요."}


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
            "attachments": [{"url": uploads.public_url(a), "filename": a.filename, "message_id": a.message_id, "label": a.label}
                            for a in inquiry.attachments],
            "can_follow_up": len(inquiry.messages) < FOLLOW_UP_LIMIT,
            # 답변 없이 종료: 고객 화면은 '답변 준비 중' 대신 '종료됨'과 이 문장 (다시 열리면 None)
            "closed_note": CLOSED_TEXT.get(inquiry.close_reason) if inquiry.status == "완료" and inquiry.close_reason else None,
            "order_number": inquiry.order_number,           # 없으면 추가 문의에서 주문번호를 받음
            "order_needs_fix": bool(inquiry.order_number) and not order_resolves(object_session(inquiry), inquiry),   # 적은 번호로 주문을 찾지 못함
            "photos_requested": inquiry.photo_request is not None,   # 파손 사진을 나중에 보내기로 함 → 추가 문의에 안내
            # 상담원이 '확인 후 다시 안내'를 표시해 둠 (확인할 내용·기한 같은 내부 정보는 보내지 않음)
            "more_answer_coming": inquiry.recheck_note is not None,
            "refund_account": refund_account.masked(inquiry),
            "refund_account_needed": refund_account.needed(object_session(inquiry), inquiry),
            "exchange_fee": exchange_fee.state(exchange_fee.order_for(object_session(inquiry), inquiry))}


FOLLOW_UP_LIMIT = 10  # 문의 1건에 추가 문의 최대 개수 (끝없는 대화 방지, 넘으면 새 문의로)
REOPEN_FROM = ("자동 처리", "완료")


def add_follow_up(db: Session, inquiry: Inquiry, content: str, tokens: list[str],
                  order_number: str | None = None, refund=None) -> CustomerMessage:
    """고객 추가 문의(내용 보충): 저장 → 사진 연결 → 끝난 문의면 다시 열어 상담원에게 (AI 재분석은 하지 않음).
    처음 문의에 주문번호가 없으면 order_number 를 문의에 붙이고, 대화에도 '(주문번호 추가: …)'로 남김"""
    if len(inquiry.messages) >= FOLLOW_UP_LIMIT:
        raise AppError(400, "이 문의에는 더 이상 추가 문의를 남길 수 없습니다. 새 문의로 남겨 주세요.", "TOO_MANY_MESSAGES")
    applies = bool(order_number) and order_number != inquiry.order_number and not order_resolves(db, inquiry)
    if content == "(주문번호 보냄)" and not applies:
        # 글 없이 주문번호만 보냈는데 이미 맞는 주문번호가 있어 쓰이지 않음 → 빈 추가 문의가 남지 않게
        raise AppError(422, "이 문의에는 이미 주문번호가 있어요. 전하실 내용을 적어 주세요.", "VALIDATION_ERROR")
    if applies:
        before = inquiry.order_number
        inquiry.order_number = order_number
        relink_open_tickets(db, inquiry)   # 처리 전 티켓도 새 주문으로
        content = f"{content}\n(주문번호 {'변경: ' + before + ' → ' if before else '추가: '}{order_number})"
    if refund:   # 환불 계좌는 글과 따로 저장 (대화에는 받았다는 표시만, 번호는 남기지 않음)
        refund_account.save(inquiry, refund.bank, refund.holder, refund.number)
        if "환불 계좌" not in content:
            content = f"{content}\n(환불 계좌 등록: {refund.bank})"
    msg = CustomerMessage(inquiry_id=inquiry.id, content=content)
    db.add(msg)
    db.flush()
    if uploads.claim(db, tokens, inquiry.id, message_id=msg.id) and inquiry.photo_request:
        inquiry.photo_request = None   # 나중에 보내기로 한 사진이 옴
    if inquiry.status in REOPEN_FROM:
        inquiry.sla_started_at = utcnow()   # 끝난 문의가 다시 열림 → 답변 기한을 지금부터 다시 셈
        inquiry.close_reason = None
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
