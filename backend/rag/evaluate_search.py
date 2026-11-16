"""FAQ 검색 평가: 고객 문장마다 검색을 돌려 정답 FAQ가 몇 위에 나오는지 잽니다.

    python -m backend.rag.evaluate_search --out evaluation/faq_search_tfidf.json          # TF-IDF
    python -m backend.rag.evaluate_search --engine kure --out evaluation/faq_search_kure.json   # KURE + ChromaDB

평가 세트: data/test/faq_retrieval.json (직접 작성한 문장, docs/faq_search_eval.md 참고)
FAQ: data/faq/faqs.csv (DB가 아니라 파일에서 읽어 언제 돌려도 같은 결과)

지표
- hit@1 / hit@3: 정답 FAQ가 1위 / 3위 안에 있는 비율 (정답이 있는 문장만)
- MRR: 정답의 순위 역수 평균 (1위=1, 2위=0.5, 3위=0.33, 그 밖=0)
- 기준값 판단: "1위 점수 ≥ 기준값이면 추천" 했을 때
    · 추천 정확도: 정답이 있는 문장에서 1위가 정답이면서 기준값을 넘은 비율
    · 걸러냄: FAQ가 없는 문장에서 1위 점수가 기준값보다 낮은 비율
  고객 화면의 FAQ 추천이 이 기준값을 씁니다 (검색 객체의 suggest_min_score).
- 가장 좋은 기준값: 위 두 비율의 평균이 가장 높은 값 (검색 방식을 바꾸면 다시 정해야 함)
"""

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "data/test/faq_retrieval.json"
FAQS = ROOT / "data/faq/faqs.csv"
K = 3


class Searcher(Protocol):
    def search(self, text: str, k: int = 3) -> list[dict]: ...


def load_faqs(path: Path = FAQS) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        return [{"id": r["id"], "category": r["category"], "question": r["question"], "answer": r["answer"]}
                for r in csv.DictReader(f)]


def load_cases(path: Path = CASES) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def _rate(part: float, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def evaluate(searcher: Searcher, cases: list[dict], threshold: float, k: int = K) -> dict:
    rows = []
    for c in cases:
        hits = searcher.search(c["text"], k)
        ids = [h["id"] for h in hits]
        expected = c["expected"]
        top = hits[0]["score"] if hits else 0.0
        rank = next((i + 1 for i, fid in enumerate(ids) if fid in expected), None)
        if expected and c.get("match") == "all":
            hit3 = all(e in ids for e in expected)
        else:
            hit3 = rank is not None
        rows.append({
            "id": c["id"], "type": c["type"], "text": c["text"], "expected": expected,
            "top": ids, "scores": [round(h["score"], 4) for h in hits], "top_score": round(top, 4),
            "rank": rank, "hit1": rank == 1, "hit3": hit3,
        })

    answerable = [r for r in rows if r["expected"]]
    unanswerable = [r for r in rows if not r["expected"]]

    def block(items: list[dict]) -> dict:
        return {
            "n": len(items),
            "hit@1": _rate(sum(r["hit1"] for r in items), len(items)),
            f"hit@{k}": _rate(sum(r["hit3"] for r in items), len(items)),
            "mrr": _rate(sum(1 / r["rank"] for r in items if r["rank"]), len(items)),
        }

    def decide(t: float) -> dict:
        accepted = sum(r["hit1"] and r["top_score"] >= t for r in answerable)
        rejected = sum(r["top_score"] < t for r in unanswerable)
        acc, rej = _rate(accepted, len(answerable)), _rate(rejected, len(unanswerable))
        return {"threshold": round(t, 2), "answer_ok": acc, "reject_ok": rej,
                "balanced": round(((acc or 0) + (rej or 0)) / 2, 4)}

    sweep = [decide(t / 100) for t in range(1, 100)]
    best = max(sweep, key=lambda d: (d["balanced"], -d["threshold"]))

    by_type = defaultdict(list)
    for r in answerable:
        by_type[r["type"]].append(r)

    def scores(items):
        s = sorted(r["top_score"] for r in items)
        return {"min": s[0], "median": s[len(s) // 2], "max": s[-1]} if s else None

    return {
        "overall": block(answerable),
        "by_type": {t: block(v) for t, v in by_type.items()},
        "threshold": {"current": decide(threshold), "best": best},
        "top_score": {"answerable": scores(answerable), "unanswerable": scores(unanswerable)},
        "misses": [r for r in answerable if not r["hit1"]],
        "false_suggest": [r for r in unanswerable if r["top_score"] >= threshold],
        "rows": rows,
    }


def make_searcher(engine: str, doc_mode: str = "qa") -> Searcher:
    if engine == "tfidf":
        from backend.rag.faq_search import FaqSearch
        return FaqSearch(load_faqs())
    if engine == "kure":
        from backend.rag.embedding_search import KureFaqSearch, load_model
        return KureFaqSearch(load_faqs(), load_model(), doc_mode=doc_mode, persist_dir=None)
    raise SystemExit(f"모르는 검색 방식: {engine}")


def main() -> None:
    p = argparse.ArgumentParser(description="FAQ 검색 평가")
    p.add_argument("--engine", default="tfidf", choices=["tfidf", "kure"], help="검색 방식")
    p.add_argument("--doc-mode", default="qa", choices=["question", "qa"],
                   help="kure: FAQ를 질문만 / 질문+답변으로 벡터화")
    p.add_argument("--cases", default=str(CASES))
    p.add_argument("--threshold", type=float, help="추천 기준값 (기본: 그 검색 방식의 고객 화면 기준값)")
    p.add_argument("--out", help="결과 JSON 저장 경로 (예: evaluation/faq_search_tfidf.json)")
    args = p.parse_args()

    import time

    t0 = time.perf_counter()
    searcher = make_searcher(args.engine, args.doc_mode)
    load_s = time.perf_counter() - t0
    cases = load_cases(Path(args.cases))
    t0 = time.perf_counter()
    threshold = args.threshold if args.threshold is not None else searcher.suggest_min_score
    report = evaluate(searcher, cases, threshold)
    per_query_ms = (time.perf_counter() - t0) / len(cases) * 1000
    engine = args.engine if args.engine == "tfidf" else f"{args.engine}-{args.doc_mode}"
    report = {"engine": engine, "timing": {"load_s": round(load_s, 2), "per_query_ms": round(per_query_ms, 1)}, **report}

    o = report["overall"]
    print(f"[{engine}] 준비 {load_s:.1f}초 · 문장당 {per_query_ms:.1f}ms")
    print(f"[{engine}] 정답 있는 문장 {o['n']}개: hit@1 {o['hit@1']:.1%} · hit@3 {o[f'hit@{K}']:.1%} · MRR {o['mrr']:.3f}")
    for t, b in report["by_type"].items():
        print(f"  {t:<8} {b['n']:>3}개: hit@1 {b['hit@1']:.1%} · hit@3 {b[f'hit@{K}']:.1%}")
    cur, best = report["threshold"]["current"], report["threshold"]["best"]
    print(f"기준값 {cur['threshold']}: 추천 정확도 {cur['answer_ok']:.1%} · FAQ 없는 문의 걸러냄 {cur['reject_ok']:.1%}")
    print(f"가장 좋은 기준값 {best['threshold']}: 추천 정확도 {best['answer_ok']:.1%} · 걸러냄 {best['reject_ok']:.1%}")
    ts = report["top_score"]
    print(f"1위 점수 중앙값: 정답 있는 문장 {ts['answerable']['median']} / FAQ 없는 문장 {ts['unanswerable']['median']}")

    if args.out:
        out = ROOT / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
