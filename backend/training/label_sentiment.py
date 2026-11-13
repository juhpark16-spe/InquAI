"""OpenAI LLM으로 문의 문장에 감정(긍정·중립·부정) 라벨을 붙입니다.

콜센터 데이터의 감정 라벨은 고객의도 이름에 '불만'이 있는지만 본 임시 라벨이라 감정 모델 학습에 쓸 수 없습니다.
docs/labeling_guide.md 3장의 감정 기준을 LLM에게 주고 문장마다 다시 라벨을 붙입니다.

준비
    1. .env.example 을 복사해 .env 로 만들고 OPENAI_API_KEY 를 채웁니다.
    2. pip install openai python-dotenv

실행 예시 (프로젝트 루트에서)
    # 1) 먼저 테스트 100건으로 LLM 라벨이 사람 라벨과 얼마나 일치하는지 확인 (비용 거의 없음)
    python backend/training/label_sentiment.py --input data/test/real_inquiries_100.csv --output data/test/real_inquiries_100_llm.csv --compare
    # 2) 학습 데이터 일부로 시험
    python backend/training/label_sentiment.py --limit 300
    # 3) 전체 라벨링 (이미 라벨링한 문장은 캐시에서 재사용하므로 다시 돈이 들지 않음)
    python backend/training/label_sentiment.py
    # 4) 감정 모델 학습
    python backend/training/train.py --data data/raw/inquiries_sentiment.csv --label-column sentiment --class-weight

결과
    data/raw/inquiries_sentiment.csv   sentiment = LLM 라벨, sentiment_rule = 기존 규칙 라벨, sentiment_source
                                       llm(LLM 라벨) / llm_fixed(근거 없는 긍정 → 중립) / human(보충 데이터 사람 라벨) / rule(LLM 실패)
    data/raw/sentiment_cache.jsonl     문장별 LLM 라벨 캐시 (prepare_data.py를 다시 돌려도 재사용)
"""

import argparse
import json
import os
import random
import re
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from labels import SENTIMENT_LABELS

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SYSTEM_PROMPT = """너는 쇼핑몰 고객 문의의 감정을 분류하는 라벨러다. 각 문장을 긍정, 중립, 부정 중 하나로 분류한다.

[기준]
- 부정: 불만·불편·실망·화남을 드러내는 문장.
  감정 표현(짜증나요, 황당하네요, 어이없어요, 기분 나빴어요), 반복·지연 강조(계속, 아직도, 벌써 몇 번째, 며칠째, 도대체),
  손해 호소, 항의·신고·책임 추궁, 비꼬는 말투, 강한 재촉(당장, 빨리 좀).
- 중립: 문제가 있어도 담담하게 묻거나 요청하는 문장. 단순 정보 요청, 사실 전달, 절차 확인.
- 긍정: 감사·칭찬·만족을 분명히 표현하는 문장. 문의가 함께 있어도 감사·칭찬이 분명하면 긍정.
  단, 형식적인 인사("수고하세요", "안녕하세요", 끝에 붙인 "감사합니다")만 있는 일반 문의는 중립.

[주의]
- 문의 유형(배송, 환불 등)이 아니라 말투와 표현으로만 판단한다. 환불 요청이라도 담담하면 중립이다.
- 콜센터 통화를 받아 적은 구어체 문장이 많다. 'ㅇㅇ'는 가려진 개인정보다.
- 애매하면 중립을 고른다.

[예시]
송장번호가 조회가 안 됩니다. → 중립
일주일째 배송 준비중이에요. 도대체 언제 보내주실 건가요? → 부정
반품하려고요. 사이즈가 작아서요. → 중립
이거 몇 번을 말해야 알아들으세요? → 부정
친절하게 처리해 주셔서 감사합니다. → 긍정
빠르게 보내주셔서 감사해요! 그런데 양말이 하나 안 왔어요. → 긍정
네 수고하세요. 주문 확인 부탁드려요. → 중립

[입력 형식] 한 줄에 '번호<TAB>문장'
[출력] 입력의 모든 번호에 대해 결과를 하나씩 반환한다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "sentiment": {"type": "string", "enum": SENTIMENT_LABELS},
                },
                "required": ["id", "sentiment"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}

# LLM이 '긍정'을 붙였어도 이런 감사·칭찬 표현이 없으면 '중립'으로 되돌립니다.
# (콜센터의 짧은 구어체 문장 "하나 취소됐어요?" 등에 LLM이 근거 없이 긍정을 붙이는 경우가 많았음)
POSITIVE_EVIDENCE = re.compile(
    "감사|고맙|고마워|좋|친절|만족|다행|응원|마음에 들|최고|훌륭|덕분|편하|편리|칭찬|감동|예쁘|맛있|기뻐|행복|든든|안심"
)

# 사람이 직접 라벨을 붙인 데이터(source_split 값). LLM에 보내지 않고 사람 라벨을 그대로 씁니다.
HUMAN_LABELED_SPLITS = {"supplement"}

usage_lock = threading.Lock()
usage = Counter()


def resolve(path: str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def label_batch(client: OpenAI, model: str, texts: list[str], retries: int = 4) -> dict[int, str]:
    """texts의 0부터 시작하는 위치 → 감정. 실패한 문장은 결과에 없음."""
    lines = "\n".join(f"{i}\t{' '.join(t.split())}" for i, t in enumerate(texts))
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": lines},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "sentiment_labels", "strict": True, "schema": SCHEMA},
                },
            )
            if resp.usage:
                with usage_lock:
                    usage["input_tokens"] += resp.usage.prompt_tokens
                    usage["output_tokens"] += resp.usage.completion_tokens
                    usage["requests"] += 1
            data = json.loads(resp.choices[0].message.content)
            return {
                r["id"]: r["sentiment"]
                for r in data["results"]
                if 0 <= r["id"] < len(texts) and r["sentiment"] in SENTIMENT_LABELS
            }
        except Exception as e:  # 네트워크 오류, 사용량 제한(429) 등 → 잠시 기다렸다 재시도
            wait = 2 ** attempt + random.random()
            print(f"  [재시도 {attempt + 1}/{retries}] {type(e).__name__}: {str(e)[:120]} ({wait:.1f}초 대기)")
            time.sleep(wait)
    return {}


def load_cache(path: Path) -> dict[str, str]:
    cache = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cache[r["text"]] = r["sentiment"]
    return cache


def label_all(client, model, texts, cache_path, batch_size, workers) -> dict[str, str]:
    """캐시에 없는 문장만 LLM에 보내고, 결과를 캐시에 바로 추가합니다."""
    results = {}
    batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool, cache_path.open("a", encoding="utf-8") as cache_file:
        futures = {pool.submit(label_batch, client, model, b): b for b in batches}
        for future in as_completed(futures):
            batch = futures[future]
            for i, sentiment in future.result().items():
                results[batch[i]] = sentiment
                cache_file.write(json.dumps({"text": batch[i], "sentiment": sentiment, "model": model},
                                            ensure_ascii=False) + "\n")
            cache_file.flush()
            done += 1
            if done % 10 == 0 or done == len(batches):
                print(f"  {done}/{len(batches)} 묶음 완료 (라벨 {len(results)}건)")
    return results


def parse_args():
    p = argparse.ArgumentParser(description="LLM 감정 라벨링")
    p.add_argument("--input", default="data/raw/inquiries.csv")
    p.add_argument("--output", default="data/raw/inquiries_sentiment.csv")
    p.add_argument("--cache", default="data/raw/sentiment_cache.jsonl")
    p.add_argument("--model", default=None, help="기본값: .env의 OPENAI_MODEL, 없으면 gpt-5-mini")
    p.add_argument("--batch-size", type=int, default=40, help="한 번의 요청에 넣을 문장 수")
    p.add_argument("--workers", type=int, default=4, help="동시에 보낼 요청 수")
    p.add_argument("--limit", type=int, default=0, help="새로 라벨링할 최대 문장 수 (0이면 전부, 시험용)")
    p.add_argument("--compare", action="store_true", help="입력의 기존 sentiment와 LLM 라벨 일치율 출력")
    return p.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 없습니다. .env.example 을 복사해 .env 를 만들고 키를 넣어 주세요.")
    model = args.model or os.getenv("OPENAI_MODEL") or "gpt-5-mini"
    client = OpenAI()

    df = pd.read_csv(resolve(args.input), encoding="utf-8-sig")
    df["text"] = df["text"].astype(str)
    cache_path = resolve(args.cache)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_cache(cache_path)

    human = df["source_split"].isin(HUMAN_LABELED_SPLITS) if "source_split" in df.columns else pd.Series(False, index=df.index)
    human_texts = set(df.loc[human, "text"])
    todo = [t for t in dict.fromkeys(df["text"]) if t not in cache and t not in human_texts]
    if args.limit:
        todo = todo[: args.limit]
    print(f"[감정 라벨링] 모델 {model} / 전체 {df['text'].nunique():,}문장 / 캐시 {len(cache):,} / 새로 라벨링 {len(todo):,}")
    if todo:
        print(f"  요청 약 {-(-len(todo) // args.batch_size)}회 (묶음 {args.batch_size}문장, 동시 {args.workers}개)")
        cache.update(label_all(client, model, todo, cache_path, args.batch_size, args.workers))
        print(f"  사용 토큰: 입력 {usage['input_tokens']:,} / 출력 {usage['output_tokens']:,} ({usage['requests']}회)")

    # 결과 합치기: LLM 라벨이 없는 문장(실패, --limit로 건너뜀)은 기존 규칙 라벨 유지
    if "sentiment" in df.columns:
        df["sentiment_rule"] = df["sentiment"]
    df["sentiment"] = df["text"].map(cache)
    df["sentiment_source"] = df["sentiment"].notna().map({True: "llm", False: "rule"})
    if "sentiment_rule" in df.columns:
        df["sentiment"] = df["sentiment"].fillna(df["sentiment_rule"])

    # 근거 없는 긍정 → 중립
    no_evidence = (df["sentiment_source"] == "llm") & (df["sentiment"] == "긍정") & ~df["text"].str.contains(POSITIVE_EVIDENCE)
    df.loc[no_evidence, "sentiment"] = "중립"
    df.loc[no_evidence, "sentiment_source"] = "llm_fixed"
    print(f"  근거 없는 긍정 → 중립: {no_evidence.sum()}건")

    # 사람 라벨 유지 (보충 데이터)
    if human.any():
        df.loc[human, "sentiment"] = df.loc[human, "sentiment_rule"]
        df.loc[human, "sentiment_source"] = "human"
        print(f"  사람 라벨 유지: {human.sum()}건")

    out = resolve(args.output)
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print("\n[감정 분포]")
    print(df.groupby(["sentiment_source", "sentiment"]).size().to_string())
    if args.compare and "sentiment_rule" in df.columns:
        llm = df[df["sentiment_source"] == "llm"]
        agree = (llm["sentiment"] == llm["sentiment_rule"]).mean()
        print(f"\n[기존 라벨과 일치율] {agree:.1%} ({len(llm)}건)")
        print(pd.crosstab(llm["sentiment_rule"], llm["sentiment"], rownames=["기존"], colnames=["LLM"]).to_string())
        diff = llm[llm["sentiment"] != llm["sentiment_rule"]]
        for _, r in diff.iterrows():
            print(f"  기존 {r['sentiment_rule']} → LLM {r['sentiment']} | {r['text']}")
    print(f"\n[저장] {out}")


if __name__ == "__main__":
    main()
