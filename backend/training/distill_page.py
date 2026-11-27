"""상품 페이지 표기 경계 증류: LLM(선생님)이 결정 질문으로 붙인 라벨로 분류 모델(학생)을 가르칩니다 (2026-11-26).

왜
    보강 세 번(docs/retraining.md 1~3차)은 '이 문장은 기타로 써 줘'처럼 만든 의도를 정답으로 썼습니다.
    만든 문장이 의도와 다르게 읽히면 틀린 정답이 섞이고, 상품 질문 쪽이 흔들렸습니다.
    서버의 표기 재확인(backend/ai/page_check.py)과 같은 결정 질문을 받은 LLM은 경계 30문장을 90/90 맞혔으므로,
    이번에는 **유형을 정하지 않고 상황만 주어 문장을 만들고, 라벨은 선생님 LLM이 3번 붙여 3번 모두 같은 것만** 씁니다.

하는 일
    1. 상황 8가지 × 상품 분야 12가지마다 문장 N개 생성 (유형 이름은 주지 않음, 말투 참고는 seed_inquiries.csv)
    2. 걸러내기: 너무 짧음, 기존 데이터와 겹침, 평가 문장과 비슷함(Jaccard 0.5), 생성 문장끼리 비슷함 (generate_weak와 같은 기준)
    3. 선생님 라벨: page_check.SYSTEM으로 3번 → 3번 같으면 그 유형, 아니면 버림
    4. 지금 분류 모델 예측을 붙여 저장 (이 컴퓨터 안에서만)

보내는 것: 상황 설명과 직접 만든 합성 문의 말투 예시, 생성된 문장뿐 (AI Hub 데이터·평가 문장 없음).

결과: data/supplement/page_distill_raw.csv(전부·버린 이유), data/supplement/page_distill.csv(학습용)
    python backend/training/distill_page.py --per-request 8
    python backend/training/distill_page.py --relabel      # 생성은 그대로, 걸러내기·라벨만 다시

2차 (--round 2, 2026-11-27)
    1차 704문장(기타 355)으로 학습하니 경계는 65.6 → 88.9로 올랐지만 페이지를 언급하는 보통 상품 질문까지 기타로 쏠림.
    → 페이지를 언급하는 상품 질문 상황 6가지를 더 만들고(page_distill2.csv),
      --mix 로 1차 기타 표기 알림은 100문장만 남기고 나머지와 합침 (page_distill_mix.csv)
    python backend/training/distill_page.py --round 2 --per-request 8
    python backend/training/distill_page.py --mix --other 100
"""

import argparse
import json
import random
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from generate_weak import (EVAL_FILES, EVAL_SIMILAR, EXISTING_FILES, SELF_SIMILAR, classify, grams, jaccard,  # noqa: E402
                           key, resolve)
from labels import SENTIMENT_LABELS  # noqa: E402
from prepare_data import MIN_TEXT_LENGTH  # noqa: E402

from backend.ai import page_check  # noqa: E402
from backend.ai.llm import LLM  # noqa: E402
from backend.core.config import get_settings  # noqa: E402

SITUATIONS = [  # 유형 이름은 주지 않음 → 라벨은 선생님이 정함
    ("두 곳 표기 다름", "구매 전에 상품 페이지 두 곳(상품명·옵션·상세 설명·스펙표·사진·목록·주의사항 등)의 정보가 서로 다르게 적혀 있다고 말함"),
    ("페이지 깨짐·오타·엉뚱한 내용", "상품 페이지의 이미지가 깨지거나, 오타가 있거나, 다른 상품 설명·사진이 들어가 있거나, 정보가 오래되었다고 말함"),
    ("가격·할인 표시", "구매 전에 페이지에 보이는 가격·정가·할인율·묶음 가격 표시가 이상하거나 곳마다 다르다고 말함 (쿠폰·결제 문제 아님)"),
    ("적힌 사양으로 쓰임 질문", "페이지에 적힌 사양·기능·인증·대상 연령을 근거로 내 상황에서 쓸 수 있는지, 더 자세히 알 수 있는지 물음. 표기가 틀렸다는 말은 없음"),
    ("사진·설명과 실물 질문", "구매 전에 사진·설명과 실물이 얼마나 비슷한지(색감·크기·두께·질감) 물음. 페이지가 틀렸다는 말은 없음"),
    ("두 표기 보고 어느 쪽인지", "페이지 두 곳의 정보가 달라 보여서 실제로는 어느 쪽이 맞는지, 실제 사양이 무엇인지 물음"),
    ("받은 물건이 표기와 달라 요청", "주문해서 받은 상품이 페이지 표기(색·크기·소재·구성·용량)와 달라서 교환이나 반품·환불을 요청함"),
    ("받은 물건이 표기와 다름만 말함", "주문해서 받은 상품이 페이지 표기와 다르다고 말하거나 원래 그런지 물음. 교환·반품 요청은 하지 않음"),
]
SITUATIONS2 = [  # 2차: 페이지를 언급하지만 틀렸다는 말이 없는 상품 질문 (실전 오답 "상세페이지 색상이랑 실제 색상이 많이 다른가요?" 같은 것)
    ("사진과 실물 차이 정도", "구매 전에 상세페이지 사진·색상과 실제 상품이 얼마나 다른지, 차이가 큰 편인지 물음. '다른가요', '차이 나나요' 같은 말을 써도 됨. 페이지가 틀렸다고 하지는 않음"),
    ("옵션끼리 차이", "구매 전에 페이지의 옵션 두 개(색상·용량·모델·세트 구성)가 어떻게 다른지, 어느 쪽이 나에게 맞는지 물음"),
    ("사이즈표 보고 추천", "상세페이지 사이즈표·치수를 보고 내 체형·공간에 어떤 사이즈가 맞는지 물음"),
    ("설명의 낯선 말 뜻", "상세 설명·스펙표에 적힌 용어·약자·수치의 뜻을 물음 (예: 데니어, IPX, 정격 출력)"),
    ("적힌 정보에 없는 것", "페이지에 나와 있지 않은 정보(무게, 원산지, 부속품, 세탁법 등)를 따로 알려 달라고 물음"),
    ("후기·사진 보고 걱정", "상세페이지 사진이나 설명을 보고 실제 사용에서 걱정되는 점(내구성·냄새·소음·보풀)을 물음"),
]
DOMAINS = ["의류", "신발·가방", "생활가전", "주방용품", "식품", "화장품", "유아용품", "가구·침구", "전자기기·액세서리",
           "문구·취미", "반려동물 용품", "스포츠·캠핑"]
STYLES = [("게시판체", "존댓말로 또박또박"), ("구어체", "말하듯 편하게, 맞춤법이 조금 틀려도 됨"),
          ("짧은 글", "한두 문장으로 짧게, 마침표·물음표를 빼기도 함")]

SUP = PROJECT_ROOT / "data/supplement"
ROUNDS = {1: (SITUATIONS, SUP / "page_distill_raw.csv", SUP / "page_distill.csv"),
          2: (SITUATIONS2, SUP / "page_distill2_raw.csv", SUP / "page_distill2.csv")}
MIX = SUP / "page_distill_mix.csv"

PROMPT = """너는 한국 온라인 쇼핑몰에 들어오는 고객 문의를 만드는 작가다. 서로 다른 고객 문의 {n}개를 만든다.

[상황] {situation}
[상품 분야] {domain}
[말투] {style}: {style_desc}
[실제 고객 말투 참고 (내용·길이는 따라 하지 않음)]
{seeds}

[규칙]
- 실제 고객이 쓴 것처럼 자연스럽게. 문장마다 상품·적힌 곳·표현·길이를 다르게 한다.
- 한 문의에는 위 상황 하나만 담는다.
- 주문번호·이름·전화번호·주소, 실제 브랜드 이름은 쓰지 않는다.
- 감정을 함께 붙인다. 대부분 중립, 일부 부정, 긍정은 드물게.
- 문장 끝에 인사말을 습관처럼 붙이지 않는다."""
SCHEMA = {"type": "object", "properties": {"items": {"type": "array", "items": {
    "type": "object", "properties": {"text": {"type": "string"}, "sentiment": {"type": "string", "enum": SENTIMENT_LABELS}},
    "required": ["text", "sentiment"], "additionalProperties": False}}}, "required": ["items"], "additionalProperties": False}


def generate(llm, job, n, seeds):
    (sit, desc), domain, (style, style_desc), rng = job
    picked = "\n".join(f"- {t}" for t in rng.sample(seeds, 2))
    content = PROMPT.format(n=n, situation=desc, domain=domain, style=style, style_desc=style_desc, seeds=picked)
    for _ in range(3):
        try:
            out, _ = llm.json("", content, SCHEMA, "inquiries", timeout=120)
            return [{"text": re.sub(r"\s*\((중립|부정|긍정)\)", "", " ".join(i["text"].split())).strip(), "sentiment": i["sentiment"], "situation": sit,
                     "domain": domain, "style": style} for i in out["items"]]
        except Exception as e:  # noqa: BLE001
            print(f"  [재시도] {sit}/{domain}: {type(e).__name__}")
    return []


def filter_rows(df):
    existing = set()
    for f in EXISTING_FILES + ["data/supplement/generated_weak4.csv", "data/supplement/page_error_balanced.csv",
                               "data/supplement/page_error_boost.csv", "data/supplement/page_distill.csv"]:
        if resolve(f).exists():
            existing |= {key(t) for t in pd.read_csv(resolve(f), encoding="utf-8-sig")["text"]}
    eval_grams = [grams(t) for f in EVAL_FILES for t in pd.read_csv(resolve(f), encoding="utf-8")["text"]]
    reasons, kept = [], []
    for t in df["text"]:
        g = grams(t)
        if len(key(t)) < MIN_TEXT_LENGTH:
            reasons.append("너무 짧음")
        elif key(t) in existing:
            reasons.append("기존 데이터와 겹침")
        elif any(jaccard(g, e) >= EVAL_SIMILAR for e in eval_grams):
            reasons.append("평가 문장과 비슷함")
        elif any(jaccard(g, k) >= SELF_SIMILAR for k in kept):
            reasons.append("생성 문장끼리 비슷함")
        else:
            reasons.append(None)
            kept.append(g)
    return df.assign(reason=reasons)


def teacher(llm, text):
    votes = []
    for _ in range(3):
        for _ in range(3):
            try:
                out, _ = llm.json(page_check.SYSTEM, text, page_check.SCHEMA, "category", timeout=60)
                votes.append(out["category"])
                break
            except Exception:  # noqa: BLE001
                pass
    return votes


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--per-request", type=int, default=8)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--relabel", action="store_true")
    p.add_argument("--round", type=int, default=1, choices=sorted(ROUNDS))
    p.add_argument("--mix", action="store_true", help="1차 기타 표기 알림을 --other개만 남기고 1·2차를 합침 (API 없음)")
    p.add_argument("--other", type=int, default=100)
    args = p.parse_args()
    if args.mix:
        return mix(args.other, args.seed)
    situations, RAW, OUT = ROUNDS[args.round]
    llm = LLM(get_settings(), patient=True)
    if args.relabel:
        df = pd.read_csv(RAW, encoding="utf-8-sig")[["text", "sentiment", "situation", "domain", "style"]]
    else:
        rng = random.Random(args.seed)
        seeds = pd.read_csv(PROJECT_ROOT / "data/supplement/seed_inquiries.csv", encoding="utf-8-sig")["text"].tolist()
        jobs = [(s, d, st, random.Random(rng.random())) for s in situations for d in DOMAINS
                for st in [STYLES[rng.randrange(len(STYLES))]]]
        with ThreadPoolExecutor(args.workers) as pool:
            rows = [r for rs in pool.map(lambda j: generate(llm, j, args.per_request, seeds), jobs) for r in rs]
        df = pd.DataFrame(rows)
        print(f"생성 {len(df)}문장")
    df = filter_rows(df)
    ok = df["reason"].isna()
    with ThreadPoolExecutor(args.workers) as pool:
        votes = list(pool.map(lambda t: teacher(llm, t), df.loc[ok, "text"]))
    df["votes"] = None
    df.loc[ok, "votes"] = ["|".join(v) for v in votes]
    for i, v in zip(df.index[ok], votes):
        if len(v) == 3 and len(set(v)) == 1:
            df.at[i, "category"] = v[0]
        else:
            df.at[i, "reason"] = "선생님 라벨이 흔들림"
    df.to_csv(RAW, index=False, encoding="utf-8-sig")
    print(df["reason"].fillna("사용").value_counts().to_string())
    kept = df[df["reason"].isna()][["text", "category", "sentiment", "situation", "domain", "style"]]
    kept = kept.rename(columns={"situation": "subtype"})
    kept = classify(kept).sample(frac=1, random_state=args.seed)
    kept.to_csv(OUT, index=False, encoding="utf-8-sig")
    print("\n[상황별 선생님 라벨]")
    print(pd.crosstab(kept["subtype"], kept["category"]).to_string())
    wrong = kept["model_pred"] != kept["category"]
    print(f"\n[저장] {OUT} ({len(kept)}건, 지금 모델과 다른 문장 {int(wrong.sum())}건)")
    print(Counter(zip(kept.loc[wrong, "category"], kept.loc[wrong, "model_pred"])).most_common(8))


def mix(other: int, seed: int):
    """1차 기타(표기 알림)는 상황별로 고르게 other개만, 1차의 나머지와 2차는 전부"""
    one = pd.read_csv(ROUNDS[1][2], encoding="utf-8-sig")
    two = pd.read_csv(ROUNDS[2][2], encoding="utf-8-sig")
    o = one[one["category"] == "기타"]
    per = o.groupby("subtype")["text"].transform("size") / len(o)
    keep = o.sample(n=min(other, len(o)), weights=per, random_state=seed)
    out = pd.concat([keep, one[one["category"] != "기타"], two]).sample(frac=1, random_state=seed)
    out.to_csv(MIX, index=False, encoding="utf-8-sig")
    print(f"[저장] {MIX} ({len(out)}건)")
    print(out["category"].value_counts().to_string())


if __name__ == "__main__":
    main()
