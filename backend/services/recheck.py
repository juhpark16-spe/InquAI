"""다시 안내 (확인 후 안내): 바로 답할 수 없는 문의에 "확인 후 다시 안내드리겠습니다"를 먼저 보낼 때 남기는 표시.

- 답변을 보낼 때 [확인 후 다시 안내]를 체크하면 확인할 내용(note)과 다시 안내할 기한(due_at)을 문의에 남김
- 표시가 남은 문의는 목록 '다시 안내' 필터·대시보드·알림(기한 1시간 전부터)에 보임
- 다음 답변을 보내면 표시가 자동으로 풀림 (다시 체크하면 새 내용·기한으로 바뀜). 답변 없이 풀 수도 있음
- 문의 상태는 그대로 '완료' (첫 답변은 이미 보냈으므로 답변 기한 초과로 보지 않음)
- 모든 변경은 작업 기록(recheck_set / recheck_clear)에 남고 문의의 처리 이력에 보임
"""

from datetime import datetime, timedelta

from fastapi import Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from backend.core.errors import AppError
from backend.database.models import AdminUser, Inquiry, as_utc, utcnow
from backend.services.audit import add_audit

MAX_DAYS = 14
KST = timedelta(hours=9)


class RecheckIn(BaseModel):
    note: str = Field(min_length=1, max_length=200)   # 확인할 내용 (예: "택배사 분실 조사 결과")
    due_at: datetime                                    # 다시 안내할 기한

    @field_validator("note")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("확인할 내용을 입력해 주세요.")
        return v.strip()


def _when(at: datetime) -> str:
    """작업 기록·처리 이력에 남길 기한 (한국 시각)"""
    return (as_utc(at) + KST).strftime("%m/%d %H:%M")


def set_recheck(db: Session, request: Request, user: AdminUser, inquiry: Inquiry, body: RecheckIn) -> None:
    due = as_utc(body.due_at)
    now = utcnow()
    if due <= now:
        raise AppError(422, "다시 안내할 기한은 지금보다 뒤여야 합니다.", "INVALID_RECHECK")
    if due > now + timedelta(days=MAX_DAYS):
        raise AppError(422, f"다시 안내할 기한은 {MAX_DAYS}일 안으로 정해 주세요.", "INVALID_RECHECK")
    before = {"note": inquiry.recheck_note, "due_at": _when(inquiry.recheck_due_at)} if inquiry.recheck_note else None
    inquiry.recheck_note, inquiry.recheck_due_at = body.note, due
    inquiry.recheck_by, inquiry.recheck_at = user.id, now
    add_audit(db, request, "recheck_set", user, "inquiry", inquiry.id, before=before,
              after={"note": body.note, "due_at": _when(due)}, summary=f"{body.note} (기한 {_when(due)})")


def clear_recheck(db: Session, request: Request, user: AdminUser, inquiry: Inquiry, reason: str) -> None:
    """reason: answered (다시 안내 답변을 보냄) / manual (답변 없이 해제)"""
    if not inquiry.recheck_note:
        return
    note = inquiry.recheck_note
    inquiry.recheck_note = inquiry.recheck_due_at = inquiry.recheck_by = inquiry.recheck_at = None
    how = "다시 안내 답변 발송" if reason == "answered" else "답변 없이 해제"
    add_audit(db, request, "recheck_clear", user, "inquiry", inquiry.id, reason=reason, note=note,
              summary=f"{note} · {how}")


def info(inquiry: Inquiry, names: dict[int, str]) -> dict | None:
    """문의 상세에 보낼 다시 안내 표시"""
    if not inquiry.recheck_note:
        return None
    return {"note": inquiry.recheck_note, "due_at": inquiry.recheck_due_at, "set_at": inquiry.recheck_at,
            "set_by": names.get(inquiry.recheck_by, "상담원"), "overdue": as_utc(inquiry.recheck_due_at) <= utcnow()}
