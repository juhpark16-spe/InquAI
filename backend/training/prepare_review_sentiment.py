"""AI Hub '속성기반 감정분석' 상품 리뷰를 감정 학습 데이터에 조금 섞습니다.

문의 데이터에는 긍정·부정 문장이 부족해서, 리뷰에서 긍정·부정 문장만 골라 보충합니다.
리뷰는 문의와 말투가 달라서 그대로 많이 넣으면 모델이 "리뷰 말투 = 감정 있음"으로 잘못 배웁니다.
그래서 아래 조건으로 일부만 고릅니다.
    - 쇼핑몰 리뷰만 사용 (SNS는 블로그 글이라 제외)
    - GeneralPolarity 1(긍정) / -1(부정)만 사용 ("0"은 칭찬·불만이 섞인 '혼합'이라 우리 '중립'과 뜻이 다름)
    - 문의와 비슷한 길이 (기본 10~80자)
    - 배송·교환·반품·불량 등 문의 상황과 가까운 리뷰를 먼저 뽑음
    - 감정별 최대 2,000건 (중립 문의가 여전히 중심이 되도록)

실행 예시 (프로젝트 루트에서)
    python backend/training/prepare_review_sentiment.py
    python backend/training/train.py --data data/raw/inquiries_sentiment_reviews.csv --label-column sentiment --class-weight --output-dir models/sentiment_reviews --report-name sentiment_reviews
"""

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT_ROOT.parent / "dataset" / "3.감정_속성기반 감정분석 데이터" / "01-1.정식개방데이터"
POLARITY = {"1": "긍정", "-1": "부정"}
INQUIRY_LIKE = re.compile(r"배송|교환|반품|환불|취소|불량|고객센터|상담|문의|파손|누락|오배송|택배|포장")


def resolve(path: str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_reviews(source: Path, min_len: int, max_len: int) -> pd.DataFrame:
    rows = []
    for f in sorted(source.glob("*/02.라벨링데이터/*/*.json")):
        for r in json.loads(f.read_text(encoding="utf-8")):
            sentiment = POLARITY.get(str(r.get("GeneralPolarity")))
            if r.get("Source") != "쇼핑몰" or not sentiment:
                continue
            text = " ".join(str(r.get("RawText", "")).split())
            if min_len <= len(text) <= max_len:
                rows.append({"text": text, "sentiment": sentiment, "domain": r.get("Domain", "")})
    return pd.DataFrame(rows).drop_duplicates(subset="text")


def sample(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """문의 상황과 가까운 리뷰를 최대 절반까지 먼저 뽑고 나머지는 무작위."""
    like = df[df["text"].str.contains(INQUIRY_LIKE)]
    first = like.sample(min(len(like), n // 2), random_state=seed)
    rest = df.drop(first.index)
    second = rest.sample(min(len(rest), n - len(first)), random_state=seed)
    return pd.concat([first, second])


def parse_args():
    p = argparse.ArgumentParser(description="리뷰 감정 데이터 보충")
    p.add_argument("--source", default=str(DEFAULT_SOURCE))
    p.add_argument("--base", default="data/raw/inquiries_sentiment.csv", help="label_sentiment.py 결과")
    p.add_argument("--output", default="data/raw/inquiries_sentiment_reviews.csv")
    p.add_argument("--test-file", default="data/test/real_inquiries_100.csv", help="이 문장들은 제외")
    p.add_argument("--per-label", type=int, default=2000, help="감정별 최대 리뷰 수")
    p.add_argument("--min-len", type=int, default=10)
    p.add_argument("--max-len", type=int, default=80)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    base = pd.read_csv(resolve(args.base), encoding="utf-8-sig")
    reviews = load_reviews(Path(args.source), args.min_len, args.max_len)
    print(f"[리뷰] 조건에 맞는 리뷰 {len(reviews):,}건 → {reviews['sentiment'].value_counts().to_dict()}")

    key = lambda s: s.str.replace(" ", "", regex=False)
    exclude = set(key(base["text"].astype(str)))
    test = resolve(args.test_file)
    if test.exists():
        exclude |= set(key(pd.read_csv(test, encoding="utf-8-sig")["text"].astype(str)))
    reviews = reviews[~key(reviews["text"]).isin(exclude)]

    picked = pd.concat(
        [sample(g, args.per_label, args.seed) for _, g in reviews.groupby("sentiment")]
    )
    picked = picked.assign(
        category="", intent="", label_rule="", source_category="리뷰", dialog_id="",
        source_split="review", sentiment_rule=picked["sentiment"], sentiment_source="review",
    )
    out = pd.concat([base, picked[[c for c in base.columns if c in picked.columns]]])
    out = out.sample(frac=1, random_state=args.seed).reset_index(drop=True)
    output = resolve(args.output)
    out.to_csv(output, index=False, encoding="utf-8-sig")

    print(f"[추가] 리뷰 {len(picked):,}건 (문의 상황 관련 {picked['text'].str.contains(INQUIRY_LIKE).sum():,}건)")
    print(picked["sentiment"].value_counts().to_string())
    print("\n[최종 감정 분포]")
    print(out["sentiment"].value_counts().to_string())
    print(f"\n[저장] {output} ({len(out):,}건)")


if __name__ == "__main__":
    main()
