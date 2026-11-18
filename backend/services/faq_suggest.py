"""FAQ 자동 추천 (4주차): AI가 자동 답변하지 못한 문의를 묶어 "이런 FAQ가 있으면 자동 처리됐을 것" 후보를 만듭니다.

1. 후보 문의: 최근 N일, AI가 자동 답변하지 않았고(초안·담당자 연결), 긴급도 높음(항의)이 아니며,
   **지금 FAQ 중 비슷한 것이 없는**(검색 1위 유사도가 고객 추천 기준값 미만) 문의.
   지금 FAQ로 다시 재므로, 관리자가 FAQ를 추가하면 그 묶음은 다음 추천에서 사라집니다.
2. 묶기: 문의 문장을 FAQ 검색과 같은 방식으로 벡터로 바꿔(KURE, 없으면 TF-IDF) 비슷한 것끼리 묶음. 2건 이상인 묶음만.
3. 초안: 묶음마다 LLM이 FAQ 질문·답변을 씁니다. 근거는 **상담원이 실제로 보낸 답변**만 쓰고,
   근거가 없는 내용은 [확인 필요: …]로 남깁니다. 관리자가 검토·수정해서 등록합니다 (자동 등록하지 않음).
"""

import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.ai.prompts import CUSTOMER_TEXT_RULE, customer_text
from backend.database.models import AgentLog, Inquiry, utcnow

logger = logging.getLogger("inquai")

# 같은 묶음으로 볼 코사인 유사도 (KURE는 뜻이 비슷하면 0.7 이상, TF-IDF는 글자가 겹쳐야 높아서 기준을 낮춤)
GROUP_SIMILARITY = {"kure": 0.7, "tfidf": 0.25}  # 시험: 같은 내용 KURE 0.87~0.88·TF-IDF 0.35~0.41, 다른 내용 0.48·0.07 이하
MAX_EXAMPLES = 5        # LLM에 보낼 묶음당 문의 수

SUGGEST_PROMPT = """너는 온라인 쇼핑몰 고객센터의 FAQ 편집자다.
아래는 AI가 자동으로 답하지 못해 상담원이 처리한, 서로 비슷한 고객 문의들과 상담원이 실제로 보낸 답변이다.
이 문의들을 대표하는 FAQ 하나(질문과 답변)를 만든다.

[규칙]
- 질문: 고객이 실제로 물어볼 말투로, 특정 주문·사람에 한정되지 않는 일반 질문 한 문장.
- 답변: [상담원 답변]에 있는 내용만 근거로, 누구에게나 똑같이 안내할 수 있는 일반 안내로 쓴다. 2~4문장, 존댓말.
  특정 고객의 주문번호·이름·금액·날짜는 쓰지 않는다. 사과·보상 약속은 쓰지 않는다.
- 상담원 답변에 없어 정책을 확인해야 하는 부분은 답변 안에 [확인 필요: 무엇]으로 남기고 check_points에도 적는다.
""" + CUSTOMER_TEXT_RULE

SUGGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "answer": {"type": "string"},
        "check_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["question", "answer", "check_points"],
    "additionalProperties": False,
}


def _latest_log(inquiry: Inquiry) -> AgentLog | None:
    return max(inquiry.agent_logs, key=lambda log: (log.created_at, log.id), default=None)


def _staff_answer(inquiry: Inquiry) -> str | None:
    sent = [r for r in inquiry.responses if r.status == "발송" and r.approved_by is not None]
    return (sent[-1].final_text or sent[-1].draft_text) if sent else None


def find_candidates(db: Session, faq_search, days: int) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    rows = db.scalars(select(Inquiry).where(Inquiry.created_at >= since)
                      .options(selectinload(Inquiry.agent_logs), selectinload(Inquiry.analysis),
                               selectinload(Inquiry.responses))).all()
    out = []
    for i in rows:
        log = _latest_log(i)
        if log is None or log.decision == "자동 답변" or (i.analysis and i.analysis.urgency == "높음"):
            continue
        text = f"{i.title} {i.content}".strip()
        hit = (faq_search.search(text, 1) or [None])[0] if faq_search else None
        if hit and hit["score"] >= faq_search.suggest_min_score:
            continue   # 이미 비슷한 FAQ가 있음
        out.append({"inquiry": i, "text": text, "category": i.analysis.category if i.analysis else log.category,
                    "nearest": {"code": hit["id"], "question": hit["question"], "score": round(hit["score"], 4)}
                    if hit else None})
    return out


def _vectors(texts: list[str], faq_search) -> tuple[np.ndarray, str]:
    if getattr(faq_search, "engine", None) == "kure":
        return np.asarray(faq_search.model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)), "kure"
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    m = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit_transform(texts)
    return normalize(m).toarray(), "tfidf"


def group(candidates: list[dict], faq_search, min_count: int) -> tuple[list[list[dict]], str]:
    """비슷한 문의끼리 묶음 (묶음의 평균 벡터와 비교해 기준 이상이면 그 묶음에, 아니면 새 묶음). 큰 묶음부터"""
    if len(candidates) < min_count:
        return [], getattr(faq_search, "engine", "tfidf")
    vecs, engine = _vectors([c["text"] for c in candidates], faq_search)
    threshold = GROUP_SIMILARITY[engine]
    groups: list[dict] = []
    for c, v in zip(candidates, vecs):
        best, score = None, threshold
        for g in groups:
            centroid = g["sum"] / np.linalg.norm(g["sum"])
            s = float(centroid @ v)
            if s >= score:
                best, score = g, s
        if best is None:
            groups.append({"items": [c], "sum": v.copy()})
        else:
            best["items"].append(c)
            best["sum"] += v
    found = [g["items"] for g in groups if len(g["items"]) >= min_count]
    return sorted(found, key=len, reverse=True), engine


def _draft(llm, items: list[dict], timeout: float) -> dict:
    examples = items[:MAX_EXAMPLES]
    lines = []
    for n, c in enumerate(examples, start=1):
        answer = _staff_answer(c["inquiry"])
        lines.append(f"[문의 {n}]\n{customer_text(c['text'])}\n[상담원 답변 {n}] {answer or '(아직 보낸 답변 없음)'}")
    result, _ = llm.json(SUGGEST_PROMPT, "\n\n".join(lines), SUGGEST_SCHEMA, "faq_suggest", timeout)
    return result


def suggest(db: Session, faq_search, llm, days: int = 30, min_count: int = 2, limit: int = 5,
            timeout: float = 20.0) -> dict:
    candidates = find_candidates(db, faq_search, days)
    groups, engine = group(candidates, faq_search, min_count)
    groups = groups[:limit]

    drafts: list[dict | None] = [None] * len(groups)
    if llm is not None and groups:
        def run(items):
            try:
                return _draft(llm, items, timeout)
            except Exception:  # noqa: BLE001  하나가 실패해도 나머지 추천은 보여 줌
                logger.exception("FAQ 추천 초안 작성 실패")
                return None
        with ThreadPoolExecutor(max_workers=3) as pool:
            drafts = list(pool.map(run, groups))

    items = []
    for g, d in zip(groups, drafts):
        # 유형은 LLM이 아니라 묶인 문의의 분류 결과(상담원이 고친 것 포함) 중 가장 많은 것 (라벨링 기준을 따르게)
        category = Counter(c["category"] for c in g).most_common(1)[0][0]
        nearest = max((c["nearest"] for c in g if c["nearest"]), key=lambda x: x["score"], default=None)
        items.append({
            "count": len(g),
            "category": category,
            "question": (d or {}).get("question") or g[0]["inquiry"].title,
            "answer": (d or {}).get("answer") or "",
            "check_points": [p for p in (d or {}).get("check_points", []) if p.strip()],
            "drafted": d is not None,
            "with_staff_answer": sum(_staff_answer(c["inquiry"]) is not None for c in g),
            "nearest_faq": nearest,
            "examples": [{"inquiry_id": c["inquiry"].id, "inquiry_number": c["inquiry"].inquiry_number,
                          "title": c["inquiry"].title, "content": c["inquiry"].content[:200]} for c in g[:MAX_EXAMPLES]],
        })
    return {"days": days, "candidates": len(candidates), "engine": engine, "items": items}
