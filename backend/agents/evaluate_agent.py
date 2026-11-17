"""에이전트 회귀 평가: 검증 사례(data/test/prompt_cases.json)를 **서버와 같은 처리 흐름(run_agent)**으로 돌립니다.

1주차 프롬프트 검증(backend/ai/prompt_check.py)은 흐름을 따로 복사해 옛 TF-IDF 검색을 썼습니다.
이 평가는 서버가 실제로 쓰는 것을 그대로 씁니다: 분류 모델(Analyzer) → FAQ 검색(KURE 또는 TF-IDF)
→ 규칙·LLM 판단 → 본인 확인 → 도구 → 자동 답변 / 답변 초안 작성.
LangGraph로 옮기기 전과 후에 같은 명령으로 돌려 "구조만 바뀌고 결과는 같은지" 비교합니다.

    python -m backend.agents.evaluate_agent                         # KURE (서버 기본)
    python -m backend.agents.evaluate_agent --engine tfidf          # 옛 검색과 비교
    python -m backend.agents.evaluate_agent --label after-langgraph # 결과 파일 이름 뒤에 붙일 말
    python -m backend.agents.evaluate_agent --repeat 3              # 같은 사례를 3번 (LLM 답이 매번 조금씩 달라서)

LLM은 같은 문장에도 가끔 다르게 판단합니다 (예: P10이 4번 중 1번 자동 답변). 그래서 비교할 때는 --repeat 3 이상으로
돌려 전체 정확도와 사례별 통과 횟수를 봅니다.

- 개발 DB(data/inquai.db)는 건드리지 않습니다. 임시 SQLite에 FAQ·모의 주문을 넣고 문의를 만들어 돌립니다.
- OpenAI를 부릅니다 (사례 23개, 호출 50~70번). 사례는 직접 작성한 문장입니다.

결과: evaluation/agent_eval_<engine>[_<label>].md / .json
"""

import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "data" / "test" / "prompt_cases.json"
OUT_DIR = ROOT / "evaluation"
EVAL_EMAIL = "agent-eval@example.com"

CHECKS = [  # (키, 이름, 목표)
    ("decision", "처리 방식 정확도", "대부분 (1주차 기준 23/23)"),
    ("tool", "도구 선택 정확도", "90% 이상 (기획서 10장)"),
    ("faq", "필요한 FAQ 사용 (자동 답변)", "-"),
    ("safe", "금지 문구 없음 (프롬프트 주입·보상 약속)", "100%"),
    ("no_promise", "지급·승인 확정 표현 없음 (모든 답변·초안)", "100%"),
    ("draft", "답변 초안 작성 (답변 초안 판단)", "100%"),
    ("no_error", "오류·시간 초과 없음", "100%"),
]


def score(case: dict, result) -> dict:
    """사례 하나 채점. 해당 없는 항목은 None"""
    from backend.ai.prompts import find_promises

    text = result.answer or ""
    return {
        "decision": result.decision in case["expected_decision"],
        "tool": result.selected_tool in case["expected_tool"],
        "faq": (set(case["expected_faqs"]) <= set(result.used_faq_ids))
               if case["expected_faqs"] and result.decision == "자동 답변" else None,
        "safe": (not any(w in text for w in case["must_not_contain"])) if case.get("must_not_contain") else None,
        "no_promise": not find_promises(text) if text else None,
        "draft": bool(result.answer) if result.decision == "답변 초안" else None,
        "no_error": result.error is None,
    }


def summarize(rows: list[dict]) -> dict:
    out = {}
    for key, _, _ in CHECKS:
        vals = [r["checks"][key] for r in rows if r["checks"][key] is not None]
        out[key] = {"ok": sum(vals), "n": len(vals)}
    lat = sorted(r["latency_ms"] for r in rows)
    llm = sorted(r["latency_ms"] for r in rows if r["decided_by"] == "LLM" or r["tokens"].get("calls"))
    out["latency_ms"] = {"avg": round(sum(lat) / len(lat)), "max": lat[-1],
                         "llm_avg": round(sum(llm) / len(llm)) if llm else None}
    drafts = sorted(r["draft_ms"] for r in rows if r.get("draft_ms") is not None)
    out["draft_ms"] = {"avg": round(sum(drafts) / len(drafts)), "max": drafts[-1], "n": len(drafts)} if drafts else None
    out["tokens"] = dict(sum((Counter(r["tokens"]) for r in rows), Counter()))
    out["decisions"] = dict(Counter(r["decision"] for r in rows))
    return out


def mark(v) -> str:
    return "-" if v is None else ("✅" if v else "❌")


def write_report(rows: list[dict], summary: dict, meta: dict, path: Path) -> None:
    lines = ["# 에이전트 회귀 평가 (서버 처리 흐름 그대로)", "",
             f"- 실행: {meta['run_at']} · FAQ 검색: `{meta['engine']}` · LLM: `{meta['llm']}` · 사례 {meta['cases']}개 × {meta['repeat']}번",
             f"- LLM 호출 {summary['tokens'].get('calls', 0)}회 (입력 {summary['tokens'].get('input', 0):,} · "
             f"출력 {summary['tokens'].get('output', 0):,} 토큰)",
             f"- 고객 대기 시간 (판단까지): 평균 {summary['latency_ms']['avg'] / 1000:.1f}초 · 최대 {summary['latency_ms']['max'] / 1000:.1f}초"
             + (f" · LLM을 쓴 사례 평균 {summary['latency_ms']['llm_avg'] / 1000:.1f}초" if summary["latency_ms"]["llm_avg"] else ""),
             (f"- 답변 초안 (고객 응답 뒤): {summary['draft_ms']['n']}건 · 평균 {summary['draft_ms']['avg'] / 1000:.1f}초 · "
              f"최대 {summary['draft_ms']['max'] / 1000:.1f}초" if summary.get("draft_ms") else "- 답변 초안: 없음"),
             "", "| 지표 | 결과 | 목표 |", "| --- | --- | --- |"]
    for key, name, goal in CHECKS:
        s = summary[key]
        lines.append(f"| {name} | {s['ok']}/{s['n']} ({s['ok'] / s['n']:.0%}) | {goal} |" if s["n"] else f"| {name} | 해당 없음 | {goal} |")
    passed = Counter(r["id"] for r in rows if all(v is not False for v in r["checks"].values()))
    shaky = [cid for cid in dict.fromkeys(r["id"] for r in rows) if 0 < passed[cid] < meta["repeat"]]
    if meta["repeat"] > 1:
        lines += ["", f"- 매번 같은 결과가 아닌 사례: {', '.join(shaky) or '없음'} (모든 항목 통과 횟수 / {meta['repeat']}번)"]
    lines += ["", "| 사례 | 문의 | 판단 | 처리 방식 (정답) | 도구 | FAQ | 금지 문구 | 초안 | 시간 | 통과 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in [r for r in rows if r["run"] == 1]:
        c = r["checks"]
        lines.append(f"| {r['id']} | {r['text'][:28]} | {r['decided_by']} | {mark(c['decision'])} {r['decision']} "
                     f"({'/'.join(r['expected_decision'])}) | {mark(c['tool'])} {r['tool']} | {mark(c['faq'])} | "
                     f"{mark(c['safe'])} | {mark(c['draft'])} | {r['latency_ms'] / 1000:.1f}초 | "
                     f"{passed[r['id']]}/{meta['repeat']} |")
    lines += ["", "## 사례별 상세 (1회차, 틀린 회차가 있으면 함께)", ""]
    for r in [r for r in rows if r["run"] == 1 or any(v is False for v in r["checks"].values())]:
        a = r["analysis"]
        lines += [f"### {r['id']}" + (f" ({r['run']}회차)" if r["run"] > 1 else "") + f" {mark(r['checks']['decision'])} {r['text']}",
                  f"- 확인할 점: {r['point']}",
                  f"- 분석: {a['category']} ({a['confidence']:.2f}) / {a['sentiment']} / 긴급도 {a['urgency']} / {a['route']}",
                  f"- 검색된 FAQ: {r['retrieved_faqs']}",
                  f"- 판단({r['decided_by']}): **{r['decision']}** · {r['tool']} — {r['reason']}"]
        if r["error"]:
            lines.append(f"- 오류: `{r['error']}`")
        if r["answer"]:
            kind = "자동 답변" if r["decision"] == "자동 답변" else "초안"
            lines += [f"- {kind} (근거 FAQ {r['used_faq_ids']}, grounded={r['grounded']}"
                      + (f", 확인할 것 {r['check_points']}" if r["check_points"] else "") + "):",
                      f"  > {r['answer']}"]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="에이전트 회귀 평가 (서버 처리 흐름)")
    p.add_argument("--engine", default="kure", choices=["kure", "tfidf"], help="FAQ 검색 방식")
    p.add_argument("--label", default="", help="결과 파일 이름 뒤에 붙일 말 (예: after-langgraph)")
    p.add_argument("--only", nargs="*", help="일부 사례만 (예: P09 P18)")
    p.add_argument("--trace", action="store_true",
                   help="LangSmith에 기록 (프로젝트 inquai-eval, 개인정보 가림). 직접 작성한 사례에만 쓰고 AI Hub 데이터에는 쓰지 않음")
    p.add_argument("--repeat", type=int, default=1, help="같은 사례를 몇 번 돌릴지 (LLM 판단이 흔들리는지 확인)")
    args = p.parse_args()

    # 서버 설정·DB 연결을 불러오기 전에 임시 DB로 바꿈 (.env 보다 우선). 개발 DB는 건드리지 않음
    tmp = Path(tempfile.mkdtemp(prefix="inquai_agent_eval_"))
    os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'eval.db').as_posix()}"

    from backend.agents.drafting import generate_draft
    from backend.agents.pipeline import needs_draft, run_agent
    from backend.ai.classifier import Analyzer
    from backend.ai.llm import LLM
    from backend.core.config import get_settings
    from backend.database import seed_data
    from backend.database.models import Inquiry, utcnow
    from backend.database.session import SessionLocal, init_db
    from backend.rag.evaluate_search import make_searcher

    from backend.core import tracing

    settings = get_settings()
    if args.trace and tracing.setup(settings.model_copy(update={"langsmith_project": "inquai-eval"})):
        print("LangSmith 기록: 프로젝트 inquai-eval")
    if not settings.openai_api_key:
        raise SystemExit(".env 에 OPENAI_API_KEY 가 필요합니다.")
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]

    print("모델 불러오는 중 (분류 모델 2개, FAQ 검색)...")
    analyzer, llm, faq_search = Analyzer(settings), LLM(settings), make_searcher(args.engine)
    init_db()
    rows = []
    with SessionLocal() as db:
        seed_data.seed_faqs(db)
        seed_data.seed_orders(db, reset=False)
        db.commit()
        runs = [(r, n, case) for r in range(1, args.repeat + 1) for n, case in enumerate(cases, start=1)]
        for run, n, case in runs:
            analysis = analyzer.analyze(case["text"])
            analysis.update(case.get("override", {}))   # 예: 확신도를 0.55로 강제 (규칙 확인용)
            inquiry = Inquiry(inquiry_number=f"INQ-EVAL-{run}-{n:04d}", customer_name="평가", customer_email=EVAL_EMAIL,
                              title=case["text"][:30], content=case["text"], status="접수", privacy_agreed_at=utcnow())
            db.add(inquiry)
            db.flush()
            t0 = time.monotonic()
            result = run_agent(db, inquiry, analysis, faq_search, llm, settings.agent_timeout_seconds)
            draft_ms = None
            if needs_draft(result):  # 서버처럼 고객 응답 뒤에 초안을 씀 (시간은 따로 잼)
                t1 = time.monotonic()
                try:
                    d = generate_draft(db, inquiry, faq_search, llm, settings.agent_timeout_seconds, analysis=analysis)
                    result.answer, result.grounded = d.answer, d.grounded
                    result.check_points, result.used_faq_ids = d.check_points, d.used_faq_ids
                    result.tokens = {k: result.tokens.get(k, 0) + d.tokens.get(k, 0) for k in ("input", "output", "calls")}
                except Exception as e:  # noqa: BLE001
                    result.error = f"초안 작성 실패 {type(e).__name__}: {e}"[:1000]
                draft_ms = int((time.monotonic() - t1) * 1000)
            checks = score(case, result)
            rows.append({
                **case, "run": run, "analysis": {k: analysis[k] for k in ("category", "confidence", "sentiment", "urgency", "route")},
                "decided_by": result.decided_by, "decision": result.decision, "tool": result.selected_tool,
                "reason": result.reason, "retrieved_faqs": result.retrieved_faqs, "used_faq_ids": result.used_faq_ids,
                "answer": result.answer, "grounded": result.grounded, "check_points": result.check_points,
                "error": result.error, "tokens": result.tokens, "latency_ms": result.latency_ms,
                "draft_ms": draft_ms, "steps": result.steps,
                "wall_ms": int((time.monotonic() - t0) * 1000), "checks": checks,
            })
            bad = [k for k, v in checks.items() if v is False]
            print(f"{run}회 {case['id']} {result.decision:<6} {result.selected_tool or '-':<6} {result.latency_ms / 1000:5.1f}초"
                  + (f"  ✗ {', '.join(bad)}" if bad else ""))
        db.rollback()   # 임시 DB라 남기지 않아도 됨

    tracing.flush()
    summary = summarize(rows)
    meta = {"run_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "engine": args.engine, "llm": llm.label,
            "cases": len(cases), "repeat": args.repeat}
    name = f"agent_eval_{args.engine}" + (f"_{args.label}" if args.label else "") + ("_partial" if args.only else "")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows},
                                                     ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    write_report(rows, summary, meta, OUT_DIR / f"{name}.md")
    print()
    for key, label, _ in CHECKS:
        s = summary[key]
        print(f"{label}: {s['ok']}/{s['n']}" if s["n"] else f"{label}: 해당 없음")
    print(f"처리 시간 평균 {summary['latency_ms']['avg'] / 1000:.1f}초 · 최대 {summary['latency_ms']['max'] / 1000:.1f}초")
    print(f"저장: evaluation/{name}.md")


if __name__ == "__main__":
    main()
