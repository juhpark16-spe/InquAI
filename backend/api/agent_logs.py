"""AI 실행 로그 API (docs/api_spec.md 9장).

    GET /api/admin/agent-logs   문의마다 에이전트가 무엇을 판단하고 어떤 도구를 썼는지 (최신순)

- 관리자는 전체, 상담원은 자신에게 배정된 문의의 로그만 봅니다 (기획서 8장).
- 필터: 문의, 처리 방식, 판단 주체, 도구, 도구 성공 여부, 문제만(오류·도구 실패·확신도 낮음), 기간(KST 날짜).
- summary는 필터에 맞는 전체 로그의 합계입니다 (현재 페이지만이 아님). 성공 지표 '도구 선택 정확도'를 볼 때도 씁니다.
"""

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from backend.ai.prompts import CONFIDENCE_THRESHOLD, DECISIONS, TOOLS
from backend.core.dependencies import DB, LoginUser
from backend.core.errors import AppError
from backend.database.models import AgentLog, Faq, Inquiry
from backend.schemas.agent_logs import AgentLogPage

router = APIRouter(prefix="/admin", tags=["AI 실행 로그"])
KST = timezone(timedelta(hours=9))
MAX_RANGE_DAYS = 92


def _summary(logs: list[AgentLog]) -> dict:
    tools: dict[str, dict] = {}
    for log in logs:
        if log.selected_tool:
            t = tools.setdefault(log.selected_tool, {"count": 0, "failed": 0})
            t["count"] += 1
            t["failed"] += log.tool_success is False
    llm = [log.latency_ms for log in logs if log.decided_by == "LLM" and log.latency_ms is not None]
    tokens = Counter()
    for log in logs:
        for k in ("input", "output", "calls"):
            tokens[k] += int((log.tokens or {}).get(k) or 0)
    return {
        "count": len(logs),
        "by_decision": {d: sum(log.decision == d for log in logs) for d in DECISIONS},
        "by_decided_by": dict(Counter(log.decided_by for log in logs)),
        "by_tool": {t: tools[t] for t in [*TOOLS, *sorted(set(tools) - set(TOOLS))] if t in tools},
        "errors": sum(bool(log.error) for log in logs),
        "tool_failures": sum(log.tool_success is False for log in logs),
        "low_confidence": sum(log.confidence < CONFIDENCE_THRESHOLD for log in logs),
        "avg_latency_ms": round(sum(llm) / len(llm)) if llm else None,
        "max_latency_ms": max(llm) if llm else None,
        "tokens": {k: tokens[k] for k in ("input", "output", "calls")},
    }


def _row(log: AgentLog) -> dict:
    i = log.inquiry
    fields = ("id", "created_at", "inquiry_id", "category", "confidence", "decision", "decided_by", "selected_tool",
              "tool_success", "tool_output", "retrieved_faqs", "used_faq_ids", "reason", "response_text", "llm_model",
              "tokens", "latency_ms", "trace_url", "steps", "error")
    return {**{k: getattr(log, k) for k in fields}, "inquiry_number": i.inquiry_number, "inquiry_title": i.title,
            "inquiry_status": i.status}


@router.get("/agent-logs", response_model=AgentLogPage, summary="AI 실행 로그 (관리자 전체, 상담원은 배정된 문의만)")
def list_agent_logs(
    user: LoginUser, db: DB,
    inquiry_id: int | None = None,
    decision: str | None = Query(None, description="자동 답변 / 답변 초안 / 담당자 연결"),
    decided_by: str | None = Query(None, description="규칙 / LLM"),
    selected_tool: str | None = Query(None, description="FAQ 검색 / 배송 조회 / 티켓 접수 / 상담원 이관"),
    tool_success: bool | None = None,
    problem: bool = Query(False, description="오류·도구 실패·확신도 0.8 미만만"),
    date_from: date | None = Query(None, alias="from", description="시작일 (KST)"),
    date_to: date | None = Query(None, alias="to", description="종료일 (KST)"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100),
):
    if decision and decision not in DECISIONS:
        raise AppError(422, f"decision 은 {', '.join(DECISIONS)} 중 하나입니다.", "INVALID_PARAM")
    if date_from and date_to and (date_to < date_from or (date_to - date_from).days >= MAX_RANGE_DAYS):
        raise AppError(422, f"기간은 시작일 이후, 최대 {MAX_RANGE_DAYS}일입니다.", "INVALID_PARAM")

    stmt = select(AgentLog).join(AgentLog.inquiry).options(joinedload(AgentLog.inquiry))
    if user.role != "admin":
        stmt = stmt.where(Inquiry.assigned_to == user.id)
    if inquiry_id is not None:
        stmt = stmt.where(AgentLog.inquiry_id == inquiry_id)
    if decision:
        stmt = stmt.where(AgentLog.decision == decision)
    if decided_by:
        stmt = stmt.where(AgentLog.decided_by == decided_by)
    if selected_tool:
        stmt = stmt.where(AgentLog.selected_tool == selected_tool)
    if tool_success is not None:
        stmt = stmt.where(AgentLog.tool_success.is_(tool_success))
    if problem:
        stmt = stmt.where(or_(AgentLog.error.is_not(None), AgentLog.tool_success.is_(False),
                              AgentLog.confidence < CONFIDENCE_THRESHOLD))
    if date_from:
        stmt = stmt.where(AgentLog.created_at >= datetime.combine(date_from, time.min, KST).astimezone(timezone.utc))
    if date_to:
        end = datetime.combine(date_to + timedelta(days=1), time.min, KST).astimezone(timezone.utc)
        stmt = stmt.where(AgentLog.created_at < end)

    # 시연 규모(수백 건)라 한 번에 읽어 합계를 내고 페이지는 잘라서 돌려줌
    logs = db.scalars(stmt.order_by(AgentLog.created_at.desc(), AgentLog.id.desc())).unique().all()
    items = logs[(page - 1) * size: page * size]
    codes = {c for log in items for c in [*(f[0] for f in log.retrieved_faqs or []), *(log.used_faq_ids or [])]}
    titles = dict(db.execute(select(Faq.code, Faq.question).where(Faq.code.in_(codes))).all()) if codes else {}
    return {"total": len(logs), "page": page, "size": size, "summary": _summary(logs),
            "items": [_row(log) for log in items], "faq_titles": titles}
