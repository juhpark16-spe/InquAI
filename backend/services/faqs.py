"""FAQ 관리: 다음 FAQ 번호, 사용 횟수, FAQ가 바뀐 뒤 검색 색인 다시 만들기."""

import logging
import re
import threading
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database.models import AgentLog, Faq

logger = logging.getLogger("inquai")
_refresh_lock = threading.Lock()


def next_code(db: Session) -> str:
    nums = [int(m.group(1)) for c in db.scalars(select(Faq.code)) if (m := re.fullmatch(r"F(\d+)", c))]
    return f"F{(max(nums) + 1 if nums else 1):02d}"


def usage(db: Session) -> dict[str, tuple[int, object]]:
    """FAQ 번호 → (근거로 쓰인 횟수, 마지막으로 쓰인 시각). AI가 실제 답변 근거로 고른 FAQ(used_faq_ids)만 셈"""
    counts, last = Counter(), {}
    for ids, at in db.execute(select(AgentLog.used_faq_ids, AgentLog.created_at)):
        for code in ids or []:
            counts[code] += 1
            if code not in last or at > last[code]:
                last[code] = at
    return {code: (n, last[code]) for code, n in counts.items()}


def refresh_search(state, db: Session) -> None:
    """활성 FAQ로 검색 색인을 새로 만들어 바꿔 끼움 (에이전트·고객 추천이 바로 새 FAQ를 씀).

    KURE는 이미 불러온 모델을 다시 쓰고 바뀐 FAQ 벡터만 다시 계산합니다 (44개 기준 GPU 1초 안팎).
    실패하면 기존 색인을 그대로 두고 기록만 남깁니다 (FAQ 저장 자체는 이미 끝남).
    """
    current = getattr(state, "faq_search", None)
    if current is None:
        return
    with _refresh_lock:
        try:
            if current.engine == "kure":
                from backend.rag.embedding_search import KureFaqSearch

                state.faq_search = KureFaqSearch.from_db(db, current.model, doc_mode=current.doc_mode)
            else:
                from backend.rag.faq_search import FaqSearch

                state.faq_search = FaqSearch.from_db(db)
            logger.info("FAQ 검색 색인을 다시 만들었습니다 (%s, %d개)", state.faq_search.engine,
                        len(state.faq_search.faqs))
        except Exception:  # noqa: BLE001
            logger.exception("FAQ 검색 색인을 다시 만들지 못했습니다. 서버를 다시 켜면 반영됩니다.")
