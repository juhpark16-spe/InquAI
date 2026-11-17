"""모델이 자주 틀리는 유형만 골라 OpenAI LLM으로 고객 문의를 생성합니다 (재학습 약점 보강, 4주차).

왜 필요한가
    상담원 분류 수정(data/test/written_pool.csv로 흉내 낸 11건)을 보면 모델이 틀리는 곳이 몰려 있습니다
    (docs/retraining.md "모델이 틀리는 곳"). 수정 11건만으로는 양이 적어서, 같은 유형의 문장을 더 만들어 보강합니다.
    - 배송 사고(누락·오배송·배송 중 파손)를 '상품'으로 봄
    - '주문 취소'를 다른 말로 하면(없던 걸로, 하나만 빼 주세요, 수량 줄이기) '기타'로 봄
    - 회원 정보·계정 문의를 '기타'로 봄, 받는 사람 변경을 '교환'으로 봄

    목표 유형은 **수정용 세트(written_pool)에서 드러난 약점만** 골랐습니다.
    평가 세트(written_eval)에서만 틀린 문장(선물 포장, 페이지 표기 오류 등)을 보고 목표를 정하면
    평가 점수가 부풀려지므로 넣지 않았습니다. 평가 세트 문장은 LLM에 보내지도 않습니다.

하는 일
    1. 약점 하위 유형(SUBTYPES) × 말투 3가지(generate_other.STYLES)마다 문장을 생성합니다.
       말투 참고용으로 data/supplement/seed_inquiries.csv(직접 만든 합성 문의, 라벨은 기준서로 고침)에서 같은 유형 2문장을 넣습니다.
    2. 걸러내기: 너무 짧음, 다른 유형으로 읽히는 단어(예: 배송 사고 문장에 '교환·반품·환불'),
       필요한 단서 없음, 기존 데이터와 겹침, **평가 세트 문장과 비슷함**(글자 3개 묶음 Jaccard 0.5 이상), 생성 문장끼리 비슷함.
    3. 남은 문장을 지금 분류 모델로 분류해(이 컴퓨터 안에서만) model_pred·model_conf를 붙입니다.
       지금 모델이 이미 맞히는 문장도 남깁니다 (틀린 문장만 넣으면 그 유형 쪽으로 너무 쏠림).

결과
    data/supplement/generated_weak.csv   text, category, sentiment, subtype, style, model_pred, model_conf
    → train.py --extra-train 으로 학습 데이터에만 더합니다 (prepare_data 기본 보충에는 넣지 않음).
    생성 문장은 꼭 일부를 사람이 읽어 보고, 이상한 문장은 지운 뒤 --refilter로 다시 정리하세요.

실행 예시 (프로젝트 루트에서)
    python backend/training/generate_weak.py --per-request 10
    python backend/training/generate_weak.py --refilter        # API 없이 걸러내기·분류만 다시
"""

import argparse
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI

from generate_other import STYLES, clean_tail
from labels import CATEGORY_LABELS, SENTIMENT_LABELS
from prepare_data import MIN_TEXT_LENGTH

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEED_FILE = "data/supplement/seed_inquiries.csv"
EVAL_FILE = "data/test/written_eval.csv"
EXISTING_FILES = ["data/raw/inquiries_with_qa.csv", "data/supplement/web_inquiries.csv",
                  "data/supplement/generated_other.csv", "data/test/real_inquiries_100.csv",
                  "data/test/external_test.csv", "data/test/written_pool.csv", EVAL_FILE]
EVAL_SIMILAR = 0.5     # 평가 문장과 글자 3개 묶음이 이만큼 겹치면 버림
SELF_SIMILAR = 0.7     # 생성 문장끼리

NO_REQUEST = r"교환|반품|환불|바꿔|바꾸|취소|돌려"
# (하위 유형, 정답 유형, 설명, 예시, 있으면 버릴 단어, 꼭 있어야 할 단어)
SUBTYPES = [
    ("누락", "배송",
     "받은 상자에 구성품·여러 개 중 일부·사은품이 빠져 있음을 알림. 교환·반품·환불 요청은 하지 않고, 빠진 게 어떻게 되는지 묻거나 보내 달라고만 함 (원칙 5)",
     "3개 묶음 샀는데 상자 열어 보니 2개만 들어 있네요", NO_REQUEST, None),
    ("오배송", "배송",
     "주문한 것과 다른 상품·색상·사이즈, 또는 남의 물건이 옴. 교환·반품·환불이라는 말 없이 알리거나 어떻게 해야 하는지 물음 (원칙 5)",
     "베이지로 주문했는데 카키색이 들어 있어요", NO_REQUEST, None),
    ("배송 중 파손", "배송",
     "택배 상자가 젖음·찌그러짐·뜯김 상태로 와서 내용물이 깨지거나 상함. 배송 과정에서 생긴 일임이 문장에 드러남 (상자 상태, 택배 언급). 교환·반품·환불 요청 없음 (원칙 5)",
     "상자가 다 찌그러져서 왔는데 안에 액자 유리가 금 갔어요", NO_REQUEST, r"상자|박스|택배|포장|배송|도착|왔"),
    ("받는 사람·배송지 변경", "배송",
     "아직 출발 전인 이번 주문의 받는 사람 이름·연락처·배송지·배송 메모를 바꾸고 싶음 (회원 정보 수정이 아님)",
     "선물이라 받는 분 성함을 바꿔야 하는데 아직 안 나갔죠?", r"교환|반품|환불|회원|계정|마이페이지", None),
    ("출고 여부", "배송",
     "주문·결제 후 상품이 출발했는지, 언제 나가는지 물음. '결제했는데', '주문했는데'처럼 결제·주문 말이 앞에 자주 붙음",
     "그저께 결제했는데 아직 안 나간 건가요", r"취소|교환|반품|환불|오류|실패", None),
    ("바꿔 말한 취소", "주문 취소",
     "출고 전 주문을 없애 달라는 요청. 절반 이상은 '취소'라는 단어 없이 다른 말로 함 (없던 걸로, 안 살게요, 주문 넣은 거 빼 주세요, 접을게요, 철회 등)",
     "어제 넣은 주문 그냥 안 할게요 보내지 마세요", r"교환|반품|환불|쿠폰|적립", None),
    ("부분 취소·수량 줄이기", "주문 취소",
     "출고 전 주문에서 일부 상품만 빼거나 수량을 줄이고 싶음",
     "5개 주문했는데 3개만 받을게요 2개는 빼 주세요", r"교환|반품|환불|쿠폰|적립", None),
    ("취소 후 환불 수단", "주문 취소",
     "이미 취소한 주문의 결제 금액이 어떤 수단(카드·계좌·적립금)으로, 언제 돌아오는지 물음. 사용한 쿠폰·적립금이 되살아나는지는 묻지 않음 (원칙 2)",
     "취소한 주문 돈은 카드로 다시 들어오나요 계좌로 들어오나요", r"교환|반품|쿠폰", r"취소"),
    ("회원 정보 변경", "쿠폰·적립금·회원",
     "계정(회원 정보)에 등록된 휴대폰 번호·주소·이메일·이름·생일을 바꾸고 싶음. 특정 주문의 배송지 변경이 아님 (원칙 7)",
     "가입할 때 쓴 이메일을 다른 걸로 바꾸고 싶어요", r"주문|배송|택배|출고|개인정보",
     r"회원|계정|가입|마이페이지|내 ?정보|프로필|아이디"),
    ("계정 문제", "쿠폰·적립금·회원",
     "비밀번호 재설정·인증 메일이나 문자가 안 옴, 로그인 잠김, 휴면 해제, 아이디 찾기, 간편 로그인 연결 (원칙 7)",
     "본인인증 문자가 안 와서 비번을 못 바꿔요", r"주문|배송|결제|앱이 ?(꺼|튕)", None),
    ("구매 전 실물 질문", "상품",
     "사기 전에 사진과 실물의 색감·크기감·질감이 얼마나 다른지 물음. 페이지 표기가 틀렸다는 말은 없음 (원칙 7 상품 페이지 표기 문제)",
     "사진이 보정된 건지 실제로 보면 더 노란가요", r"교환|반품|환불|틀렸|잘못|다르게 (나와|적혀)", None),
]

# 생성 문장을 사람이 읽고 뺀 문장 (2026-11-17 검토). --refilter 때도 다시 빠집니다.
REVIEWED_OUT = [
    ("방금 결제직전인데 안 살게요 주문 넣은거 빼 주세요", "결제 전인지 주문 후인지 모호"),
    ("선물이라 수취인 이름 안 보이게 해주시면 감사해요", "요청이 무엇인지 모호"),
    ("사이즈 표기가 잘못된 옷이 왔습니다; 라벨은 L인데 실제로는 꽉 끼네요.", "받은 상품 사이즈 문제 = 상품"),
    ("사이즈 표기랑 달라서 입을 수가 없네요", "받은 상품 사이즈 문제 = 상품"),
    ("카라 색상이 사진과 다르게 왔습니다, 배송 과정에서 실수가 있었는지 궁금합니다.", "설명과 다름 = 상품"),
    ("상품 설명에는 블랙으로 되어 있었는데 회색 제품이 왔습니다. 확인 부탁드립니다.", "설명과 다름인지 오배송인지 모호"),
    ("진한네이비 주문했는데 연한네이비가왔어요 색차이가좀있는거같은데 확인만요", "색 차이 정도 = 상품"),
    ("색이 다르긴 한데 의외로 예뻐서 일단 괜찮아요", "색 차이 정도 = 상품"),
    ("색상은 예상과 다르지만 품질 자체는 좋아 보입니다, 확인 부탁드립니다.", "예상과 다름 = 상품"),
    ("취소했는데 결제할때적립금 사용했어요 환불은 적립금으로 다시 들어오나요 얼마나걸리나요", "사용한 적립금 복원 = 쿠폰 (원칙 4)"),
    ("상품취소했고 결제는 적립금+카드로 이중결제된거같아요 환불은 각각 어떻게,언제들어오나요", "적립금·카드 섞임"),
    ("결제 취소했는데 계좌로 며칠 내 입금되나요", "주문 취소인지 결제 취소인지 모호"),
    ("마이페이지에서 이름 수정 시 계속 오류가 발생합니다. 빨리 변경할 수 있는 방법 알려주세요.", "화면 오류 = 기타일 수 있음"),
]
# LLM이 실제 값 대신 넣은 자리 표시 → 보충 데이터 관례('ㅇㅇ')로
PLACEHOLDERS = {"[새이름]": "ㅇㅇㅇ", "[새번호]": "010-ㅇㅇㅇㅇ-ㅇㅇㅇㅇ", "[새주소]": "ㅇㅇ동 ㅇㅇ아파트"}

PROMPT = """너는 한국 온라인 쇼핑몰에 들어오는 고객 문의를 만드는 작가다.
아래 조건에 맞는 서로 다른 고객 문의 {n}개를 만든다.

[유형] {category} - {subtype}: {desc}
[예시] {example}
[말투] {style}: {style_desc}
[실제 고객 말투 참고 (내용·길이는 따라 하지 않음)]
{seeds}

[규칙]
- 실제 고객이 쓴 것처럼 자연스럽게. 문장마다 상품·상황·표현·길이를 다르게 한다. 예시 문장을 바꿔 쓰지 않는다.
- 한 문의에는 위 내용 하나만 담는다. 다른 요청(교환·반품·환불 등)을 섞지 않는다.
- 주문번호·이름·전화번호·주소 같은 실제 값은 쓰지 않는다. 실제 브랜드 이름도 쓰지 않는다.
- 감정을 함께 붙인다. 대부분은 중립(담담한 문의·요청), 일부는 부정(불만·답답함을 드러냄, 느낌표를 남발하지 않음), 긍정은 드물게.
- 문장 끝에 인사말을 습관처럼 붙이지 않는다. 대부분은 질문·요청으로 바로 끝난다."""

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "sentiment": {"type": "string", "enum": SENTIMENT_LABELS}},
        "required": ["text", "sentiment"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def resolve(path: str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def key(text: str) -> str:
    return re.sub(r"[\s.,!?~ㅠㅜ;]", "", str(text))


def grams(text: str) -> set:
    k = key(text)
    return {k[i:i + 3] for i in range(len(k) - 2)}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def generate(client, model, subtype, style, n, seeds, rng, retries=3):
    name, category, desc, example, _, _ = subtype
    style_name, style_desc = style
    pool = seeds[seeds["category"] == category]["text"].tolist()
    picked = "\n".join(f"- {t}" for t in rng.sample(pool, min(2, len(pool))))
    content = PROMPT.format(n=n, category=category, subtype=name, desc=desc, example=example,
                            style=style_name, style_desc=style_desc, seeds=picked)
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": content}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "inquiries", "strict": True, "schema": SCHEMA}},
            )
            items = json.loads(resp.choices[0].message.content)["items"]
            return [{"text": " ".join(i["text"].split()), "category": category, "sentiment": i["sentiment"],
                     "subtype": name, "style": style_name} for i in items]
        except Exception as e:  # 네트워크 오류, 사용량 제한 등
            print(f"  [재시도 {attempt + 1}/{retries}] {name}/{style_name}: {type(e).__name__}: {str(e)[:100]}")
    return []


def filter_rows(df: pd.DataFrame) -> pd.DataFrame:
    """reason 칸이 비어 있으면 사용."""
    df = df.copy()
    for k, v in PLACEHOLDERS.items():
        df["text"] = df["text"].str.replace(k, v, regex=False)
    df["text"] = df["text"].map(clean_tail)
    rules = {s[0]: (s[4], s[5]) for s in SUBTYPES}
    reviewed = {key(t): f"사람 검토: {w}" for t, w in REVIEWED_OUT}

    def reason(row):
        if key(row.text) in reviewed:
            return reviewed[key(row.text)]
        if re.search(r"\[[^\]]*\]", row.text):
            return "자리 표시 남음"
        if len(key(row.text)) < MIN_TEXT_LENGTH:
            return "너무 짧음"
        drop, need = rules[row.subtype]
        if drop and re.search(drop, row.text):
            return "다른 유형 단어"
        if need and not re.search(need, row.text):
            return "단서 단어 없음"
        return None

    df["reason"] = [reason(r) for r in df.itertuples()]

    existing = set()
    for f in EXISTING_FILES:
        if resolve(f).exists():
            existing |= {key(t) for t in pd.read_csv(resolve(f), encoding="utf-8-sig")["text"]}
    df.loc[df["reason"].isna() & df["text"].map(key).isin(existing), "reason"] = "기존 데이터와 겹침"

    eval_grams = [grams(t) for t in pd.read_csv(resolve(EVAL_FILE), encoding="utf-8")["text"]]
    kept = []
    for i, row in df[df["reason"].isna()].iterrows():
        g = grams(row.text)
        if any(jaccard(g, e) >= EVAL_SIMILAR for e in eval_grams):
            df.at[i, "reason"] = "평가 문장과 비슷함"
        elif any(jaccard(g, k) >= SELF_SIMILAR for k in kept):
            df.at[i, "reason"] = "생성 문장끼리 비슷함"
        else:
            kept.append(g)
    print(df["reason"].fillna("사용").value_counts().to_string())
    return df


def classify(df: pd.DataFrame) -> pd.DataFrame:
    """지금 서버의 분류 모델로 분류 (이 컴퓨터 안에서만)."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model_dir = PROJECT_ROOT / "models" / "category_classifier"
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir).eval()
    preds, confs = [], []
    with torch.no_grad():
        for i in range(0, len(df), 64):
            enc = tok(df["text"].iloc[i:i + 64].tolist(), truncation=True, max_length=256, padding=True,
                      return_tensors="pt")
            prob = model(**enc).logits.softmax(-1)
            conf, idx = prob.max(-1)
            preds += [model.config.id2label[int(j)] for j in idx]
            confs += [round(float(c), 4) for c in conf]
    return df.assign(model_pred=preds, model_conf=confs)


def save(kept: pd.DataFrame, out: Path, seed: int):
    kept = classify(kept[["text", "category", "sentiment", "subtype", "style"]]).sample(frac=1, random_state=seed)
    kept.to_csv(out, index=False, encoding="utf-8-sig")
    wrong = kept["model_pred"] != kept["category"]
    summary = kept.assign(wrong=wrong).groupby(["category", "subtype"]).agg(n=("text", "size"), wrong=("wrong", "sum"))
    print(f"\n[하위 유형별 문장 수 / 지금 모델이 틀린 수]\n{summary.to_string()}")
    print(f"\n[감정]\n{kept['sentiment'].value_counts().to_string()}")
    print(f"\n[저장] {out} ({len(kept)}건, 지금 모델이 틀린 문장 {int(wrong.sum())}건)"
          " - 일부를 직접 읽어 보고 이상한 문장은 지워 주세요.")


def parse_args():
    p = argparse.ArgumentParser(description="약점 유형 문의 생성 (재학습 보강)")
    p.add_argument("--output", default="data/supplement/generated_weak.csv")
    p.add_argument("--model", default=None, help="기본값: .env의 OPENAI_MODEL, 없으면 gpt-5-mini")
    p.add_argument("--per-request", type=int, default=10, help="하위 유형·말투 조합마다 생성할 문장 수")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--refilter", action="store_true",
                   help="새로 생성하지 않고 --output 파일에 걸러내기·분류만 다시 적용 (API 비용 없음)")
    return p.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    out = resolve(args.output)
    assert {s[1] for s in SUBTYPES} <= set(CATEGORY_LABELS)
    if args.refilter:
        df = pd.read_csv(out, encoding="utf-8-sig")
        print(f"[다시 걸러내기] {out.name} {len(df)}건")
        df = filter_rows(df.drop(columns=["model_pred", "model_conf"], errors="ignore"))
        save(df[df["reason"].isna()], out, args.seed)
        return

    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 없습니다. .env 를 확인해 주세요.")
    model = args.model or os.getenv("OPENAI_MODEL") or "gpt-5-mini"
    client = OpenAI()
    seeds = pd.read_csv(resolve(SEED_FILE), encoding="utf-8-sig")
    rng = random.Random(args.seed)

    jobs = [(s, st, random.Random(rng.random())) for s in SUBTYPES for st in STYLES]
    print(f"[생성] 모델 {model} / 요청 {len(jobs)}회 × {args.per_request}문장")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = pool.map(lambda j: generate(client, model, j[0], j[1], args.per_request, seeds, j[2]), jobs)
    df = pd.DataFrame([r for batch in results for r in batch])
    print(f"  생성 {len(df)}건")
    raw = out.with_name(out.stem + "_raw.csv")      # 걸러내기 전 원본 (다시 생성하지 않고 기준을 바꿔 볼 때)
    df.to_csv(raw, index=False, encoding="utf-8-sig")

    df = filter_rows(df)
    save(df[df["reason"].isna()], out, args.seed)


if __name__ == "__main__":
    main()
