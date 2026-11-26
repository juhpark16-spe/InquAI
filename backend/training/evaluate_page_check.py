"""표기 재확인 평가: 분류 모델만 / 분류 모델 + LLM 재확인(신호가 있을 때만)을 같은 문장으로 비교합니다.

    python -m backend.training.evaluate_page_check            # 표기 오류 경계 30문장 + 실전 100건, 3번
    python -m backend.training.evaluate_page_check --repeat 1

보내는 문장: data/test/page_error_eval.csv(직접 쓴 문장)와 real_inquiries_100.csv 중 신호가 켜진 것뿐 (AI Hub 데이터 없음).
결과: reports/page_check_eval.json
"""

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from backend.ai import page_check
from backend.ai.llm import LLM
from backend.core.config import get_settings
from backend.training.predict import InquiryClassifier

ROOT = Path(__file__).resolve().parents[2]
FILES = {"표기 경계 30": "data/test/page_error_eval.csv", "실전 100": "data/test/real_inquiries_100.csv"}


def ask(llm, text):
    for _ in range(3):
        try:
            out, usage = llm.json(page_check.SYSTEM, text, page_check.SCHEMA, "category", timeout=30)
            return out["category"], usage.get("input", 0)
        except Exception as e:  # noqa: BLE001
            err = e
    return f"오류 {type(err).__name__}", 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repeat", type=int, default=3)
    args = p.parse_args()
    settings = get_settings()
    clf, llm = InquiryClassifier(settings.category_model_dir), LLM(settings)
    report = {"model": settings.category_model_version, "llm": llm.label, "repeat": args.repeat, "sets": {}}
    for name, path in FILES.items():
        d = pd.read_csv(ROOT / path)
        d["model"] = [r["label"] for r in clf.predict(d["text"].tolist())]
        d["signal"] = d["text"].map(page_check.has_page_signal)
        idx = d.index[d["signal"]].tolist()
        jobs = [(r, i) for r in range(args.repeat) for i in idx]
        with ThreadPoolExecutor(6) as pool:
            answers = list(pool.map(lambda j: ask(llm, d.loc[j[1], "text"]), jobs))
        runs, wrong, tokens = [], Counter(), []
        for r in range(args.repeat):
            final = d["model"].copy()
            for (rr, i), (cat, tok) in zip(jobs, answers):
                if rr == r:
                    tokens.append(tok)
                    if cat in page_check.CATEGORIES and ({cat, d.loc[i, "model"]} & page_check.BOUNDARY):
                        final[i] = cat   # 서버와 같은 규칙 (page_check.apply_recheck)
            ok = final == d["category"]
            runs.append(int(ok.sum()))
            for i in d.index[~ok]:
                wrong[(d.loc[i, "text"][:40], d.loc[i, "category"], d.loc[i, "model"], final[i])] += 1
        base = int((d["model"] == d["category"]).sum())
        report["sets"][name] = {
            "문장 수": len(d), "신호가 켜진 문장": len(idx), "분류 모델만 정답": base, "재확인 후 정답(번마다)": runs,
            "재확인으로 바뀐 정답→오답": sum(1 for (t, g, m, f), n in wrong.items() if m == g and f != g),
            "입력 토큰 평균": round(sum(tokens) / len(tokens)) if tokens else 0,
            "틀린 것 (문장 | 정답 | 모델 → 최종 ×번)": [f"{t} | {g} | {m} → {f} ×{n}" for (t, g, m, f), n in wrong.most_common()],
        }
    out = ROOT / "reports" / "page_check_eval.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
