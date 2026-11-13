"""학습된 분류 모델을 직접 만든 실전 테스트 문의로 평가합니다.

train.py의 평가 데이터는 학습 데이터와 같은 콜센터 출처라서 점수가 높게 나오기 쉽습니다.
이 스크립트는 웹 문의 폼에 실제로 들어올 법한 문장으로 다시 평가합니다.

테스트 파일 형식 (CSV, UTF-8)
    text,category,sentiment,difficulty,note
    - difficulty: 보통 / 애매 (두 유형에 걸치는 문장)  → 난이도별 정확도를 따로 계산

실행 예시 (프로젝트 루트에서)
    python backend/training/evaluate.py
    python backend/training/evaluate.py --model-dir models/category_kcelectra --report-name category_kcelectra

결과
    evaluation/<report-name>_real_test_report.json   정확도, Macro F1, 혼동 행렬, 틀린 문장 목록
"""

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score

from labels import LABEL_SETS
from predict import InquiryClassifier

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def resolve(path: str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_args():
    p = argparse.ArgumentParser(description="실전 테스트 문의로 모델 평가")
    p.add_argument("--test-file", default="data/test/real_inquiries_100.csv")
    p.add_argument("--model-dir", default="models/category_classifier")
    p.add_argument("--label-column", default="category", choices=list(LABEL_SETS))
    p.add_argument("--report-name", default=None, help="기본값: <label>")
    return p.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    labels = LABEL_SETS[args.label_column]
    df = pd.read_csv(resolve(args.test_file), encoding="utf-8-sig")

    clf = InquiryClassifier(resolve(args.model_dir))
    clf.predict("워밍업")  # 첫 호출은 GPU 준비 때문에 느리므로 속도 측정에서 제외

    # 실제 서비스처럼 한 건씩 분류하며 응답 시간 측정
    preds, confs, times = [], [], []
    for text in df["text"]:
        start = time.perf_counter()
        result = clf.predict(text)[0]
        times.append((time.perf_counter() - start) * 1000)
        preds.append(result["label"])
        confs.append(result["confidence"])
    df["pred"] = preds
    df["confidence"] = confs
    df["correct"] = df["pred"] == df[args.label_column]

    y_true, y_pred = df[args.label_column], df["pred"]
    report = classification_report(y_true, y_pred, labels=labels, digits=4, zero_division=0)
    print(f"\n[실전 테스트 결과] {len(df)}건\n{report}")

    if "difficulty" in df.columns:
        print("[난이도별 정확도]")
        for level, g in df.groupby("difficulty"):
            print(f"  {level}: {g['correct'].mean():.1%} ({g['correct'].sum()}/{len(g)})")

    print("\n[확신도]")
    print(f"  맞힌 문장 평균: {df.loc[df['correct'], 'confidence'].mean():.3f}")
    if (~df["correct"]).any():
        print(f"  틀린 문장 평균: {df.loc[~df['correct'], 'confidence'].mean():.3f}")
    print(f"\n[응답 속도] 한 건 평균 {sum(times) / len(times):.1f}ms")

    wrong = df[~df["correct"]]
    print(f"\n[틀린 문장] {len(wrong)}건")
    for _, r in wrong.iterrows():
        note = f" ({r['note']})" if "note" in r and pd.notna(r["note"]) else ""
        print(f"  정답 {r[args.label_column]} → 예측 {r['pred']} ({r['confidence']:.2f}) | {r['text']}{note}")

    result = {
        "model_dir": str(args.model_dir),
        "test_file": args.test_file,
        "num_samples": len(df),
        "accuracy": accuracy_score(y_true, y_pred),
        "macro_f1": f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0),
        "accuracy_by_difficulty": (
            df.groupby("difficulty")["correct"].mean().to_dict() if "difficulty" in df.columns else None
        ),
        "avg_latency_ms": sum(times) / len(times),
        "classification_report": classification_report(
            y_true, y_pred, labels=labels, output_dict=True, zero_division=0
        ),
        "confusion_matrix": {
            "labels": labels,
            "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        },
        "errors": wrong[["text", args.label_column, "pred", "confidence"]].to_dict(orient="records"),
    }
    out = PROJECT_ROOT / "evaluation" / f"{args.report_name or args.label_column}_real_test_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[저장] {out}")
    print(f"accuracy={result['accuracy']:.4f}  macro_f1={result['macro_f1']:.4f}")


if __name__ == "__main__":
    main()
