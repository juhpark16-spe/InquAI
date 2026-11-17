"""답변 초안을 고객 응답 뒤에 쓰기 (FastAPI BackgroundTasks).

에이전트가 '답변 초안'으로 판단하면 고객에게는 바로 "접수되었습니다"를 보여 주고, 초안은 그 뒤에 씁니다.
(전에는 판단 + 초안을 한 번에 해서 고객이 10~15초 기다렸고, 20초 제한에 걸리기도 했음 — docs/agent_eval.md)

- 요청과 다른 DB 세션을 씀 (요청 세션은 응답과 함께 닫힘)
- 결과는 문의의 AI 실행 기록(agent_logs)에 더함: 초안 글, 토큰, 실패하면 "초안 작성 실패 …"
- 실패해도 문의는 그대로 '검토 대기'이고, 상담원이 [AI 초안 만들기] 버튼으로 다시 만들 수 있음
"""

import logging

from sqlalchemy import select

from backend.agents.drafting import generate_draft
from backend.database.models import AgentLog, Inquiry, Response
from backend.database.session import SessionLocal

logger = logging.getLogger("inquai")


def write_draft(inquiry_id: int, faq_search, llm, timeout: float) -> None:
    with SessionLocal() as db:
        inquiry = db.get(Inquiry, inquiry_id)
        if inquiry is None or inquiry.status != "검토 대기":
            return
        if db.scalar(select(Response).where(Response.inquiry_id == inquiry_id, Response.status == "초안")):
            return  # 그사이 상담원이 초안을 만들었으면 건드리지 않음
        log = db.scalar(select(AgentLog).where(AgentLog.inquiry_id == inquiry_id).order_by(AgentLog.id.desc()).limit(1))
        try:
            d = generate_draft(db, inquiry, faq_search, llm, timeout)
        except Exception as e:  # noqa: BLE001
            logger.exception("답변 초안 작성 실패: %s", inquiry.inquiry_number)
            if log is not None:
                log.error = f"초안 작성 실패 {type(e).__name__}: {e}"[:1000]
                log.reason = (log.reason or "") + " / 초안 작성 실패"
            db.commit()
            return
        db.add(Response(inquiry_id=inquiry_id, draft_text=d.answer, generated_by="llm", used_faq_ids=d.used_faq_ids,
                        grounded=d.grounded, check_points=d.check_points or None, status="초안"))
        if log is not None:
            log.response_text = d.answer
            log.used_faq_ids = d.used_faq_ids
            log.llm_model = log.llm_model or d.llm_model
            t = dict(log.tokens or {})
            log.tokens = {k: t.get(k, 0) + d.tokens.get(k, 0) for k in ("input", "output", "calls")}
            log.tool_output = {**(log.tool_output or {}), "draft_ms": d.latency_ms}
        db.commit()
