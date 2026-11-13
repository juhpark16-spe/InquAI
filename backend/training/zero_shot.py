"""Zero-shot 비교 실험: 파인튜닝 없이 LLM 프롬프트만으로 문의 유형·감정을 분류합니다 (기획서 5장 평가, 4주차).

같은 테스트 파일로 파인튜닝 모델(evaluate.py)과 정확도·속도·토큰을 비교합니다.
프롬프트에는 docs/labeling_guide.md 1장(유형 정의)과 3장(감정 기준)의 요약만 넣고 예시 문장은 넣지 않습니다.

실행 예시 (프로젝트 루트에서)
    python backend/training/zero_shot.py --test-file data/test/real_inquiries_100.csv
    python backend/training/zero_shot.py --latency 10        # 문의 1건씩 10번 호출해 응답 시간 측정

결과: evaluation/<report-name>_zero_shot_report.json
"""

import argparse
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from sklearn.metrics import classification_report, f1_score

from labels import CATEGORY_LABELS, SENTIMENT_LABELS

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PROMPT = """너는 온라인 쇼핑몰 고객 문의를 분류한다. 문의마다 유형 하나와 감정 하나를 고른다.

[유형]
- 배송: 아직 받지 못했거나 막 받은 첫 배송 (일정, 조회, 배송지, 배송비, 오배송·누락·파손)
- 주문 취소: 출고 전 주문을 없애는 것과 그 진행 상황 (취소 후 결제 취소·환불 반영 포함)
- 교환: 받은 상품을 다른 사이즈·색상·새 제품으로 바꾸는 것과 그 진행 상황
- 반품·환불: 받은 상품을 돌려보내고 돈을 돌려받는 것과 그 진행 상황
- 결제: 결제 수단·결제 과정 (결제 오류, 중복 결제, 할부, 입금, 영수증, 카드사 혜택)
- 상품: 상품 자체 (재고, 사이즈 추천, 소재, 색상, 사용법, AS, 요청 없는 불량 신고)
- 쿠폰·적립금·회원: 쇼핑몰이 주는 혜택과 계정 (쿠폰, 적립금, 포인트, 등급, 회원가입, 로그인, 회원정보)
- 기타: 위에 속하지 않는 문의 (새 주문 방법, 입점·제휴, 고객센터, 개인정보, 앱 오류, 칭찬·불만,
  상품 페이지의 표기가 틀렸거나 서로 다르다고 알리는 문의. 설명을 근거로 사양만 묻는 것은 상품)
고객이 원하는 행동(요청)이 분명하면 그 행동의 유형이고, 요청이 없으면 문제의 원인 유형이다.

[감정]
- 부정: 불만·불편·실망을 드러냄 (감정 표현, 반복·지연 강조, 항의, 강한 재촉)
- 긍정: 감사·칭찬·만족이 분명함
- 중립: 담담한 문의·요청 (문제가 있어도 담담하면 중립)

[입력] 한 줄에 '번호<TAB>문의'. [출력] 모든 번호에 대해 결과를 하나씩."""

SCHEMA = {
    "type": "object",
    "properties": {"results": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"},
                       "category": {"type": "string", "enum": CATEGORY_LABELS},
                       "sentiment": {"type": "string", "enum": SENTIMENT_LABELS}},
        "required": ["id", "category", "sentiment"], "additionalProperties": False}}},
    "required": ["results"], "additionalProperties": False,
}

usage = Counter()


def classify(client, model, effort, texts):
    lines = "\n".join(f"{i}\t{' '.join(t.split())}" for i, t in enumerate(texts))
    extra = {"reasoning_effort": effort} if effort else {}
    start = time.time()
    resp = client.chat.completions.create(
        model=model, **extra,
        messages=[{"role": "system", "content": PROMPT}, {"role": "user", "content": lines}],
        response_format={"type": "json_schema", "json_schema": {"name": "cls", "strict": True, "schema": SCHEMA}},
    )
    usage["input"] += resp.usage.prompt_tokens
    usage["output"] += resp.usage.completion_tokens
    usage["calls"] += 1
    rows = json.loads(resp.choices[0].message.content)["results"]
    return {r["id"]: r for r in rows}, time.time() - start


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="Zero-shot LLM 분류 비교")
    p.add_argument("--test-file", default="data/test/real_inquiries_100.csv")
    p.add_argument("--model", default=None)
    p.add_argument("--reasoning-effort", default="low", choices=["minimal", "low", "medium", "high"])
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--latency", type=int, default=10, help="1건씩 호출해 응답 시간을 잴 문의 수 (0이면 생략)")
    p.add_argument("--report-name", default=None)
    args = p.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 없습니다. .env 를 확인해 주세요.")
    model = args.model or os.getenv("OPENAI_MODEL") or "gpt-5-mini"
    client = OpenAI()

    df = pd.read_csv(PROJECT_ROOT / args.test_file, encoding="utf-8-sig")
    texts = df["text"].astype(str).tolist()
    batches = [list(range(i, min(i + args.batch_size, len(texts)))) for i in range(0, len(texts), args.batch_size)]
    pred_c, pred_s = [None] * len(texts), [None] * len(texts)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for idx, (res, _) in zip(batches, pool.map(lambda b: classify(client, model, args.reasoning_effort,
                                                                       [texts[i] for i in b]), batches)):
            for j, i in enumerate(idx):
                if j in res:
                    pred_c[i], pred_s[i] = res[j]["category"], res[j]["sentiment"]
    batch_usage = dict(usage)

    latencies = []
    for t in texts[: args.latency]:
        _, sec = classify(client, model, args.reasoning_effort, [t])
        latencies.append(sec)

    report = {"model": f"{model} (reasoning_effort={args.reasoning_effort})", "test_file": args.test_file,
              "num_samples": len(texts), "missing": sum(c is None for c in pred_c),
              "batch_usage": batch_usage,
              "single_call_latency_sec": {"mean": round(sum(latencies) / max(len(latencies), 1), 2),
                                          "max": round(max(latencies, default=0), 2), "n": len(latencies)}}
    for col, labels, pred in [("category", CATEGORY_LABELS, pred_c), ("sentiment", SENTIMENT_LABELS, pred_s)]:
        if col not in df.columns:
            continue
        y = df[col].tolist()
        yp = [x or "기타" for x in pred]
        acc = sum(a == b for a, b in zip(y, yp)) / len(y)
        report[col] = {"accuracy": acc, "macro_f1": f1_score(y, yp, labels=labels, average="macro", zero_division=0),
                       "errors": [{"text": t, "label": a, "pred": b} for t, a, b in zip(texts, y, yp) if a != b]}
        print(f"\n[{col}] 정확도 {acc:.1%}  Macro F1 {report[col]['macro_f1']:.4f}")
        print(classification_report(y, yp, labels=labels, digits=3, zero_division=0))
        for e in report[col]["errors"]:
            print(f"  정답 {e['label']} → 예측 {e['pred']} | {e['text']}")
    print(f"\n[토큰] 분류 {len(texts)}건: 입력 {batch_usage['input']:,} / 출력 {batch_usage['output']:,} ({batch_usage['calls']}회)")
    print(f"[응답 시간] 1건씩 호출 평균 {report['single_call_latency_sec']['mean']}초 (최대 {report['single_call_latency_sec']['max']}초)")

    name = args.report_name or Path(args.test_file).stem
    out = PROJECT_ROOT / "evaluation" / f"{name}_zero_shot_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[저장] {out}")


if __name__ == "__main__":
    main()
