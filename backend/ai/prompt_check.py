"""[1주차 기록용] LLM 프롬프트 검증 (기획서 9장 1주차: 처리 경로 판단·FAQ 답변, 10~20개 사례).

※ 3주차부터는 서버와 같은 처리 흐름(KURE·LangGraph·초안)을 그대로 돌리는 backend/agents/evaluate_agent.py 를 씁니다.
  이 파일은 1주차 결과(evaluation/prompt_check_*.md)를 다시 만들 때만 씁니다.

data/test/prompt_cases.json의 사례마다 실제 흐름을 그대로 돌립니다.
    분류 모델(유형·감정·확신도) → 규칙(경로·긴급도·무조건 이관) → FAQ 검색 → LLM 경로 판단 → LLM FAQ 답변
FAQ 검색은 아직 ChromaDB(3주차) 전이라, 글자 단위 TF-IDF로 비슷한 FAQ 3개를 찾는 임시 검색을 씁니다.

결과
    evaluation/prompt_check_report.md   요약 지표 + 사례별 판단 이유·답변 (FAQ 근거 일치는 사람이 직접 검수)
    evaluation/prompt_check_result.json

실행 (프로젝트 루트에서)
    python backend/ai/prompt_check.py
    python backend/ai/prompt_check.py --only P05 P18    # 일부 사례만
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT_ROOT / "backend" / "ai"), str(PROJECT_ROOT / "backend" / "training")]

from predict import InquiryClassifier  # noqa: E402
from prompts import (ANSWER_PROMPT, ANSWER_SCHEMA, ROUTE_PROMPT, ROUTE_SCHEMA,  # noqa: E402
                     decide_by_rule, format_answer_input, format_route_input)
from rules import get_route, get_urgency  # noqa: E402

usage = Counter()


class FaqSearch:
    """임시 FAQ 검색: 질문+답변을 글자 2~4개 단위 TF-IDF로 비교 (3주차에 KURE-v1 + ChromaDB로 교체)."""

    def __init__(self, path: Path):
        self.faqs = pd.read_csv(path, encoding="utf-8-sig").to_dict("records")
        docs = [f"{f['question']} {f['question']} {f['answer']}" for f in self.faqs]  # 질문에 가중치
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4)).fit(docs)
        self.matrix = self.vec.transform(docs)

    def search(self, text: str, k: int = 3) -> list[dict]:
        scores = cosine_similarity(self.vec.transform([text]), self.matrix)[0]
        return [{**self.faqs[i], "score": float(scores[i])} for i in scores.argsort()[::-1][:k]]


REASONING = {}  # main()에서 --reasoning-effort를 주면 {'reasoning_effort': 'low'} 등으로 채움


def call_llm(client, model, system, user, schema, name):
    start = time.time()
    resp = client.chat.completions.create(
        model=model, **REASONING,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
    )
    if resp.usage:
        usage["input"] += resp.usage.prompt_tokens
        usage["output"] += resp.usage.completion_tokens
        usage["calls"] += 1
    return json.loads(resp.choices[0].message.content), time.time() - start


def run_case(case, cat_model, sen_model, faq, client, model):
    text = case["text"]
    c, s = cat_model.predict(text)[0], sen_model.predict(text)[0]
    analysis = {"category": c["label"], "confidence": c["confidence"], "sentiment": s["label"]}
    analysis.update(case.get("override", {}))
    analysis["route"] = get_route(analysis["category"])
    analysis["urgency"] = get_urgency(analysis["category"], analysis["sentiment"], text)
    retrieved = faq.search(text)

    route = decide_by_rule(analysis["route"], analysis["urgency"], analysis["confidence"])
    by = "규칙"
    seconds = 0.0
    if route is None:
        route, seconds = call_llm(client, model, ROUTE_PROMPT, format_route_input(text, analysis, retrieved),
                                  ROUTE_SCHEMA, "route")
        by = "LLM"

    answer = None
    final = route["decision"]
    if route["decision"] == "자동 답변":
        chosen = [f for f in retrieved if f["id"] in route["faq_ids"]] or retrieved
        answer, sec = call_llm(client, model, ANSWER_PROMPT, format_answer_input(text, chosen), ANSWER_SCHEMA, "answer")
        seconds += sec
        if not answer["grounded"]:  # 기획서 10장: 근거가 없으면 자동 발송하지 않고 초안으로
            final = "답변 초안"

    used = set(answer["used_faq_ids"]) if answer else set(route["faq_ids"])
    checks = {
        "decision": final in case["expected_decision"],
        "tool": route["tool"] in case["expected_tool"],
        "faq": (set(case["expected_faqs"]) <= used) if case["expected_faqs"] and final == "자동 답변" else None,
        "safe": (not any(w in (answer or {}).get("answer", "") for w in case.get("must_not_contain", [])))
                if case.get("must_not_contain") else None,
    }
    return {**case, "analysis": analysis, "retrieved": [(f["id"], round(f["score"], 3)) for f in retrieved],
            "by": by, "route": route, "answer": answer, "final_decision": final, "checks": checks,
            "seconds": round(seconds, 2)}


def mark(v):
    return "-" if v is None else ("✅" if v else "❌")


def write_report(results, model, path):
    def rate(key):
        vals = [r["checks"][key] for r in results if r["checks"][key] is not None]
        return sum(vals), len(vals)

    lines = [f"# LLM 프롬프트 검증 결과", "", f"- 모델: `{model}` / 사례 {len(results)}개 / "
             f"LLM 호출 {usage['calls']}회 (입력 {usage['input']:,} · 출력 {usage['output']:,} 토큰)", ""]
    lines += ["| 지표 | 결과 | 목표 (기획서 10장) |", "| --- | --- | --- |"]
    for key, name, goal in [("decision", "처리 방식 정확도", "대부분 (1주차 통과 기준)"),
                            ("tool", "도구 선택 정확도", "90% 이상"),
                            ("faq", "필요한 FAQ 사용 (자동 답변)", "-"),
                            ("safe", "금지 문구 없음 (프롬프트 주입)", "100%")]:
        ok, n = rate(key)
        lines.append(f"| {name} | {ok}/{n} ({ok / n:.0%}) | {goal} |" if n else f"| {name} | 해당 없음 | {goal} |")
    lines += ["", "FAQ 답변 근거 일치율(목표 90%)은 아래 자동 답변을 사람이 읽고 '근거 일치' 칸에 직접 표시합니다.", "",
              "| 사례 | 문의 | 판단 | 처리 방식 (정답) | 도구 | FAQ | 근거 일치 (직접 검수) |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        ck = r["checks"]
        lines.append(f"| {r['id']} | {r['text'][:30]} | {r['by']} | {mark(ck['decision'])} {r['final_decision']} "
                     f"({'/'.join(r['expected_decision'])}) | {mark(ck['tool'])} {r['route']['tool']} | "
                     f"{mark(ck['faq'])} | {'☐' if r['answer'] else '-'} |")
    lines += ["", "## 사례별 상세", ""]
    for r in results:
        a = r["analysis"]
        lines += [f"### {r['id']} {mark(r['checks']['decision'])} {r['text']}",
                  f"- 확인할 점: {r['point']}",
                  f"- 분석: {a['category']} ({a['confidence']:.2f}) / {a['sentiment']} / 긴급도 {a['urgency']} / {a['route']}",
                  f"- 검색된 FAQ: {r['retrieved']}",
                  f"- 판단({r['by']}): **{r['route']['decision']}** · {r['route']['tool']} · FAQ {r['route']['faq_ids']}"
                  f" — {r['route']['reason']}"]
        if r["answer"]:
            lines += [f"- 답변 (근거 FAQ {r['answer']['used_faq_ids']}, grounded={r['answer']['grounded']}"
                      f"{' → 초안으로 전환' if r['final_decision'] != r['route']['decision'] else ''}):",
                      f"  > {r['answer']['answer']}"]
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="LLM 프롬프트 검증")
    p.add_argument("--cases", default="data/test/prompt_cases.json")
    p.add_argument("--faq", default="data/faq/faqs.csv")
    p.add_argument("--model", default=None)
    p.add_argument("--only", nargs="*", help="이 사례 id만 실행")
    p.add_argument("--reasoning-effort", choices=["minimal", "low", "medium", "high"], default="low",
                   help="gpt-5 계열의 내부 추론 강도. 23개 사례 비교에서 low가 정확도 100%%·평균 8초로 가장 균형이 좋았음 "
                        "(medium 16초·도구 96%%, minimal 4초·도구 87%%)")
    p.add_argument("--report-name", default="prompt_check", help="결과 파일 이름 앞부분")
    args = p.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 없습니다. .env 를 확인해 주세요.")
    model = args.model or os.getenv("OPENAI_MODEL") or "gpt-5-mini"
    if args.reasoning_effort:
        REASONING["reasoning_effort"] = args.reasoning_effort
    client = OpenAI()

    cases = json.loads((PROJECT_ROOT / args.cases).read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]
    cat_model = InquiryClassifier(PROJECT_ROOT / "models" / "category_classifier")
    sen_model = InquiryClassifier(PROJECT_ROOT / "models" / "sentiment_classifier")
    faq = FaqSearch(PROJECT_ROOT / args.faq)

    results = []
    for case in cases:
        r = run_case(case, cat_model, sen_model, faq, client, model)
        results.append(r)
        ck = r["checks"]
        print(f"{r['id']} {mark(ck['decision'])} {r['final_decision']:<6} (정답 {'/'.join(r['expected_decision'])}) "
              f"도구 {mark(ck['tool'])} {r['route']['tool']} | FAQ {mark(ck['faq'])} | {r['by']} {r['seconds']}초")

    out = PROJECT_ROOT / "evaluation"
    (out / f"{args.report_name}_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(results, f"{model} (reasoning_effort={args.reasoning_effort or '기본'})", out / f"{args.report_name}_report.md")
    ok = sum(r["checks"]["decision"] for r in results)
    print(f"\n처리 방식 {ok}/{len(results)} / LLM 호출 {usage['calls']}회 · 토큰 {usage['input']:,}+{usage['output']:,}")
    secs = [r['seconds'] for r in results if r['by'] == 'LLM']
    print(f"LLM 판단 사례 평균 {sum(secs) / max(len(secs), 1):.1f}초")
    print(f"[저장] {out / (args.report_name + '_report.md')}")


if __name__ == "__main__":
    main()
