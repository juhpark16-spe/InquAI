"""효과 지표: 자동 답변 비율 · 문의 1건당 비용 · 처리 시간 (12/3 최종 점검용, 2026-11-28).

시연 DB의 문의를 **서버와 같은 흐름으로 다시 처리**해서 잽니다. 시연 데이터의 처리 결과(seed_demo)는 미리 정해 넣은 값이라
그대로 세면 실제 AI 성능이 아니기 때문입니다.

    python -m backend.agents.measure_effect                 # 시연 DB(data/inquai.db)의 모든 문의 × 1번
    python -m backend.agents.measure_effect --limit 10      # 앞 10건만 (시험용)
    python -m backend.agents.measure_effect --repeat 2 --label after-reset

순서 (문의마다)
    1. 시연 DB를 임시 폴더에 복사 → 원본 DB는 건드리지 않음 (주문·고객·FAQ·답변 문구는 복사본 그대로 씀)
    2. 같은 고객·주문번호·제목·내용으로 새 문의를 만들어 분류 모델 → 에이전트(run_agent) → 답변 초안 판단이면 초안 작성
       (서버의 문의 등록과 같음. 추가 문의·사진은 넣지 않고 처음 문의만)
    3. 처리 방식, 판단 주체(규칙/LLM), 고객 대기 시간(판단까지), 초안 작성 시간, LLM 토큰을 기록

지표
    - 자동 답변 비율: 상담원 손을 거치지 않고 AI가 바로 답한 문의 / 전체
    - 답변 초안 비율: AI가 초안을 써 두고 상담원이 검토·발송 / 전체 (상담원이 처음부터 쓰지 않아도 됨)
    - 담당자 연결 비율: 규칙(긴급·확신도 낮음·기타) 또는 LLM이 사람에게 넘김 / 전체
    - 문의 1건당 LLM 비용: (분류는 내 PC 모델이라 0원) 판단·답변·초안·표기 재확인 토큰 × 요금표 (evaluate_drafts.PRICES)
    - 처리 시간: 고객 대기(문의 등록 → 자동 답변·접수 확인까지), 초안 작성(고객 응답 뒤, 상담원이 열기 전까지)

- 시연 데이터는 합성이라 OpenAI로 보내도 됩니다. 실제 고객 문의가 든 DB에는 쓰지 않습니다 (개인 정보가 LLM으로 감).
- 결과: evaluation/effect_metrics[_<label>].md / .json
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "evaluation"
DECISIONS = ["자동 답변", "답변 초안", "담당자 연결"]


def pct(values: list[float], p: float) -> float:
    """백분위 (p=0.5 중앙값, 0.9 = 10건 중 9건이 이 안에)"""
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))] if s else 0


def summarize(rows: list[dict], model: str) -> dict:
    from backend.agents.evaluate_drafts import USD_KRW, cost_usd

    n = len(rows)
    ok = [r for r in rows if not r["error"]]
    by = Counter(r["decision"] for r in rows)
    out = {"inquiries": n, "errors": n - len(ok),
           "decisions": {d: {"n": by.get(d, 0), "rate": round(by.get(d, 0) / n, 3) if n else 0} for d in DECISIONS},
           "decided_by": dict(Counter(r["decided_by"] for r in rows))}
    wait = [r["latency_ms"] / 1000 for r in rows]
    draft = [r["draft_ms"] / 1000 for r in rows if r["draft_ms"] is not None]
    out["wait_s"] = {"avg": round(sum(wait) / len(wait), 1) if wait else 0, "p50": round(pct(wait, 0.5), 1),
                     "p90": round(pct(wait, 0.9), 1), "max": round(max(wait, default=0), 1)}
    out["draft_s"] = ({"n": len(draft), "avg": round(sum(draft) / len(draft), 1), "max": round(max(draft), 1)}
                      if draft else None)
    tokens = sum((Counter(r["tokens"]) for r in rows), Counter())
    out["tokens"] = dict(tokens)
    usd = cost_usd(model, tokens)
    out["cost"] = ({"total_usd": round(usd, 4), "per_inquiry_usd": round(usd / n, 5),
                    "per_inquiry_krw": round(usd / n * USD_KRW, 2)} if usd is not None and n else None)
    per = {}
    for d in DECISIONS:
        rs = [r for r in rows if r["decision"] == d]
        c = cost_usd(model, sum((Counter(r["tokens"]) for r in rs), Counter())) if rs else None
        per[d] = {"n": len(rs), "krw": round(c / len(rs) * USD_KRW, 2) if c is not None and rs else None,
                  "wait_s": round(sum(r["latency_ms"] for r in rs) / len(rs) / 1000, 1) if rs else None}
    out["per_decision"] = per
    out["by_category"] = {}
    for cat in sorted({r["category"] for r in rows}):
        rs = [r for r in rows if r["category"] == cat]
        out["by_category"][cat] = {"n": len(rs), "auto": sum(r["decision"] == "자동 답변" for r in rs)}
    return out


def write_report(rows: list[dict], s: dict, meta: dict, path: Path) -> None:
    d = s["decisions"]
    cost = s["cost"]
    lines = ["# 효과 지표 (시연 데이터를 서버 흐름으로 다시 처리)", "",
             f"- 실행: {meta['run_at']} · LLM: `{meta['llm']}` · 문의 {meta['inquiries']}건 × {meta['repeat']}번"
             f" (원본: `{meta['source']}`)",
             f"- 오류·시간 초과: {s['errors']}건", "",
             "| 지표 | 결과 |", "| --- | --- |",
             f"| **자동 답변 비율** (AI가 바로 답함) | **{d['자동 답변']['rate']:.0%}** ({d['자동 답변']['n']}/{s['inquiries']}) |",
             f"| 답변 초안 비율 (AI 초안 → 상담원 검토) | {d['답변 초안']['rate']:.0%} ({d['답변 초안']['n']}/{s['inquiries']}) |",
             f"| 담당자 연결 비율 (사람에게 넘김) | {d['담당자 연결']['rate']:.0%} ({d['담당자 연결']['n']}/{s['inquiries']}) |",
             f"| AI가 처리하거나 초안을 쓴 비율 | {d['자동 답변']['rate'] + d['답변 초안']['rate']:.0%} |",
             f"| **문의 1건당 LLM 비용** | **" + (f"약 {cost['per_inquiry_krw']:.1f}원 (${cost['per_inquiry_usd']:.4f})" if cost else "-") + "** |",
             f"| **고객 대기 시간** (판단·자동 답변까지) | **평균 {s['wait_s']['avg']}초** · 중앙값 {s['wait_s']['p50']}초 · "
             f"90% {s['wait_s']['p90']}초 · 최대 {s['wait_s']['max']}초 |",
             "| 초안 작성 시간 (고객 응답 뒤) | " + (f"평균 {s['draft_s']['avg']}초 · 최대 {s['draft_s']['max']}초 ({s['draft_s']['n']}건)"
                                            if s["draft_s"] else "-") + " |",
             f"| 판단 주체 | " + ", ".join(f"{k} {v}건" for k, v in s["decided_by"].items()) + " |",
             f"| LLM 토큰 합 | 입력 {s['tokens'].get('input', 0):,} · 출력 {s['tokens'].get('output', 0):,} · 호출 {s['tokens'].get('calls', 0)}회 |",
             "", "| 처리 방식 | 건수 | 1건당 비용 | 고객 대기 평균 |", "| --- | --- | --- | --- |"]
    for k, v in s["per_decision"].items():
        lines.append(f"| {k} | {v['n']} | " + (f"{v['krw']:.1f}원" if v["krw"] is not None else "-")
                     + " | " + (f"{v['wait_s']}초" if v["wait_s"] is not None else "-") + " |")
    lines += ["", "| 유형 (분류 결과) | 문의 | 자동 답변 |", "| --- | --- | --- |"]
    lines += [f"| {c} | {v['n']} | {v['auto']} |" for c, v in s["by_category"].items()]
    lines += ["", "- 비용은 100만 토큰당 요금표(`backend/agents/evaluate_drafts.py` PRICES)로 계산한 추정. 분류 모델은 서버 안에서 돌아 0원.",
              "- 고객 대기 시간에는 분류 모델 시간이 빠져 있음 (서버에서 문의 등록 1건 분류는 보통 0.1초 안팎).",
              "", "## 문의별 (1회차)", "", "| 원래 번호 | 제목 | 유형 | 판단 | 처리 방식 | 대기 | 초안 | 토큰(입력·출력) |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in [r for r in rows if r["run"] == 1]:
        lines.append(f"| {r['source_number']} | {r['title'][:20]} | {r['category']} | {r['decided_by']} | {r['decision']} | "
                     f"{r['latency_ms'] / 1000:.1f}초 | " + (f"{r['draft_ms'] / 1000:.1f}초" if r["draft_ms"] is not None else "-")
                     + f" | {r['tokens'].get('input', 0):,}·{r['tokens'].get('output', 0):,} |"
                     + (f" 오류: {r['error'][:60]}" if r["error"] else ""))
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="효과 지표 (자동 답변 비율·1건당 비용·처리 시간)")
    p.add_argument("--db", default=str(ROOT / "data" / "inquai.db"), help="시연 DB (SQLite 파일)")
    p.add_argument("--limit", type=int, help="앞에서부터 N건만")
    p.add_argument("--repeat", type=int, default=1)
    p.add_argument("--label", default="")
    args = p.parse_args()

    src = Path(args.db)
    if not src.exists():
        raise SystemExit(f"DB 파일이 없습니다: {src} (먼저 python -m backend.database.seed_demo --reset)")
    tmp = Path(tempfile.mkdtemp(prefix="inquai_effect_"))
    shutil.copy2(src, tmp / "effect.db")   # 원본 DB는 건드리지 않음
    os.environ["DATABASE_URL"] = f"sqlite:///{(tmp / 'effect.db').as_posix()}"

    from sqlalchemy import select

    from backend.agents.drafting import generate_draft
    from backend.agents.pipeline import needs_draft, run_agent
    from backend.ai.classifier import Analyzer
    from backend.ai.llm import LLM
    from backend.core.config import get_settings, llm_connection
    from backend.database.models import Inquiry, utcnow
    from backend.database.session import SessionLocal, init_db
    from backend.rag.evaluate_search import make_searcher

    settings = get_settings()
    if not llm_connection(settings)[0]:
        raise SystemExit(".env 에 LLM API 키가 필요합니다.")
    print("모델 불러오는 중 (분류 모델 2개, FAQ 검색)...")
    analyzer, llm, faq_search = Analyzer(settings), LLM(settings, patient=True), make_searcher("kure")
    init_db()   # 복사본이 옛 구조면 빠진 칸을 채움
    rows = []
    with SessionLocal() as db:
        originals = db.scalars(select(Inquiry).order_by(Inquiry.id)).all()
        if args.limit:
            originals = originals[:args.limit]
        source = [(q.inquiry_number, q.customer_name, q.customer_email, q.order_number, q.title,
                   q.content, q.photo_request) for q in originals]
        print(f"문의 {len(source)}건 × {args.repeat}번")
        for run in range(1, args.repeat + 1):
            for n, (number, name, email, order, title, content, photo) in enumerate(source, start=1):
                inquiry = Inquiry(inquiry_number=f"INQ-EFF-{run}-{n:04d}", customer_name=name, customer_email=email,
                                  order_number=order, title=title, content=content, status="접수",
                                  privacy_agreed_at=utcnow(), photo_request=photo)
                db.add(inquiry)
                db.flush()
                analysis = analyzer.analyze(content)   # 서버(services/inquiries.py)와 같이 본문으로 분류
                result = run_agent(db, inquiry, analysis, faq_search, llm, settings.agent_timeout_seconds)
                analysis = result.analysis or analysis
                tokens = dict(result.tokens or {})
                draft_ms, error = None, result.error
                if needs_draft(result):   # 서버처럼 고객 응답 뒤에 초안
                    t1 = time.monotonic()
                    try:
                        d = generate_draft(db, inquiry, faq_search, llm, settings.agent_timeout_seconds, analysis=analysis)
                        tokens = {k: tokens.get(k, 0) + d.tokens.get(k, 0) for k in ("input", "output", "calls")}
                    except Exception as e:  # noqa: BLE001
                        error = f"초안 작성 실패 {type(e).__name__}: {e}"[:300]
                    draft_ms = int((time.monotonic() - t1) * 1000)
                rows.append({"run": run, "source_number": number, "title": title, "category": analysis["category"],
                             "decision": result.decision, "decided_by": result.decided_by, "latency_ms": result.latency_ms,
                             "draft_ms": draft_ms, "tokens": tokens, "error": error})
                print(f"{run}회 {n:3d}/{len(source)} {number} {result.decision:<6} {result.decided_by:<3} "
                      f"{result.latency_ms / 1000:5.1f}초" + (f" + 초안 {draft_ms / 1000:.1f}초" if draft_ms else "")
                      + (f"  ✗ {error[:50]}" if error else ""))
        db.rollback()
    shutil.rmtree(tmp, ignore_errors=True)

    summary = summarize(rows, llm.label)
    meta = {"run_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "llm": llm.label, "inquiries": len(source),
            "repeat": args.repeat, "source": src.relative_to(ROOT).as_posix() if src.is_relative_to(ROOT) else src.name}
    name = "effect_metrics" + (f"_{args.label}" if args.label else "") + ("_partial" if args.limit else "")
    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / f"{name}.json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
    write_report(rows, summary, meta, OUT_DIR / f"{name}.md")
    d = summary["decisions"]
    print(f"\n자동 답변 {d['자동 답변']['rate']:.0%} · 초안 {d['답변 초안']['rate']:.0%} · 담당자 {d['담당자 연결']['rate']:.0%}")
    if summary["cost"]:
        print(f"1건당 LLM 비용 약 {summary['cost']['per_inquiry_krw']:.1f}원")
    print(f"고객 대기 평균 {summary['wait_s']['avg']}초 · 90% {summary['wait_s']['p90']}초")
    print(f"저장: evaluation/{name}.md")


if __name__ == "__main__":
    main()
