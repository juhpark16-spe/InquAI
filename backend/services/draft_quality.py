"""AI 초안 수정 분석: 상담원이 AI 초안을 얼마나, 어떻게 고쳐서 보냈는지 (GET /api/stats/drafts).

대상: 상담원이 승인해서 보낸 AI 초안 (generated_by="llm", status="발송", approved_by 있음).
      자동 발송(approved_by 없음)과 상담원이 처음부터 직접 쓴 답변은 비교할 초안이 없어 뺍니다.

- 수정 정도 change = 1 - 글자 단위 유사도 (difflib). 0 = 그대로, 1 = 완전히 새로 씀
- 단계: 그대로(글자 하나 안 바꿈) / 조금 고침(change < 0.2, 인사말·한 문장 다듬기) / 많이 고침
- 고친 방식: 덧붙임(지운 것 없이 더함) / 줄임(더한 것 없이 지움) / 고쳐 씀(지우고 새로 씀)
- AI 글 비율 ai_share = 보낸 답변 글자 중 AI 초안에서 그대로 온 글자의 비율
- 예시의 비교(segments)는 띄어쓰기 단위로 나눠 보여 줌 (글자 단위는 한국어에서 읽기 어려움)
"""

import re
from difflib import SequenceMatcher

LIGHT_EDIT = 0.2
LEVELS = ("그대로", "조금 고침", "많이 고침")
KINDS = ("덧붙임", "줄임", "고쳐 씀")


def compare(draft: str, final: str) -> dict:
    """초안과 보낸 답변 비교: 수정 정도, 단계, 고친 방식, AI 글 비율, 더한·지운 글자 수"""
    draft, final = draft.strip(), final.strip()
    if draft == final:
        return {"change": 0.0, "level": "그대로", "kind": None, "ai_share": 1.0, "added": 0, "removed": 0}
    m = SequenceMatcher(None, draft, final, autojunk=False)
    added = removed = 0
    for op, i1, i2, j1, j2 in m.get_opcodes():
        if op in ("replace", "delete"):
            removed += i2 - i1
        if op in ("replace", "insert"):
            added += j2 - j1
    kept = sum(b.size for b in m.get_matching_blocks())
    change = round(1 - m.ratio(), 4)
    return {
        "change": change,
        "level": "조금 고침" if change < LIGHT_EDIT else "많이 고침",
        "kind": "덧붙임" if removed == 0 else "줄임" if added == 0 else "고쳐 씀",
        "ai_share": round(kept / len(final), 4) if final else 0.0,
        "added": added,
        "removed": removed,
    }


def segments(draft: str, final: str) -> list[dict]:
    """초안 → 보낸 답변 비교를 띄어쓰기 단위 조각으로: op = same(그대로) / del(지움) / add(더함)"""
    a = re.findall(r"\s+|\S+", draft.strip())
    b = re.findall(r"\s+|\S+", final.strip())
    out: list[dict] = []

    def push(op: str, text: str) -> None:
        if not text:
            return
        if out and out[-1]["op"] == op:
            out[-1]["text"] += text
        else:
            out.append({"op": op, "text": text})

    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            push("same", "".join(a[i1:i2]))
        else:
            push("del", "".join(a[i1:i2]))
            push("add", "".join(b[j1:j2]))
    return out
