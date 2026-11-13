"""AI Hub '소상공인 고객 주문 질의-응답'(4번)과 '용도별 목적대화'(2번) 데이터를 학습·평가에 더합니다.

왜 필요한가
    기존 학습 데이터(콜센터)는 통화를 받아 적은 말투라 실제 서비스(웹·채팅 문의)와 다릅니다.
    4번 데이터는 고객이 상품 Q&A에 직접 쓴 짧은 질문이라 실제 서비스 말투와 같습니다.

하는 일
    1. 4번 고객 질문의 인텐트(예: 배송_날짜_질문)를 우리 8개 유형으로 옮깁니다. (INTENT_RULES)
       - 음식점·카페·병원·슈퍼처럼 오프라인 매장 질문은 뺍니다.
       - 문장에 그 유형의 근거 단어가 없거나(TEXT_EVIDENCE), 교환·반품·취소처럼 다른 유형 단어가 섞이면 뺍니다.
    2. 감성 라벨: m → 중립, n → 부정. n은 기준이 우리보다 넓어서 불만 표현(NEG_EVIDENCE)이 있는 문장만 부정으로 씁니다.
       p(긍정)는 대부분 단순 질문이라 쓰지 않습니다.
    3. 2번 데이터에서 사람이 '부정감정표현하기'로 표시한 고객 문장을 부정 감정 보충으로 씁니다.
    4. 4번 Validation(학습에 쓰지 않는 다른 사람들의 문의)으로 외부 테스트를 만듭니다.

결과
    data/raw/qa_category.csv                     4번에서 뽑은 유형 학습용 문장
    data/raw/inquiries_with_qa.csv               기존 유형 데이터 + 4번       → 유형 모델 학습
    data/raw/inquiries_sentiment_with_qa.csv     기존 감정 데이터 + 4번 + 2번 → 감정 모델 학습
    data/test/external_test.csv                  외부 테스트 (인텐트로 자동 라벨, AI Hub 데이터라 git 제외)

실행 예시 (프로젝트 루트에서, prepare_data.py와 label_sentiment.py를 먼저 실행)
    python backend/training/prepare_qa_data.py
"""

import argparse
import glob
import json
import re
import sys
from pathlib import Path

import pandas as pd

from labels import CATEGORY_LABELS
from prepare_data import CARD_BENEFIT, MIN_TEXT_LENGTH, TEXT_EVIDENCE

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATASET_ROOT = PROJECT_ROOT.parent / "dataset"
QA_SOURCE = next(iter(DATASET_ROOT.glob("4.질의응답보충_소상공인*")), None)
DIALOG_SOURCE = DATASET_ROOT / "2.문의유형보충_용도별 목적대화 데이터" / "01.데이터"

OFFLINE_DOMAINS = {"음식점", "카페", "병원", "슈퍼"}

# 인텐트 앞부분 → 유형 (위에서부터 먼저 맞는 규칙 사용, None이면 버림)
INTENT_RULES = [
    (r"^결제_취소", None),                      # 결제 취소 = 주문 취소인지 결제인지 애매
    (r"^(주문|구매)_취소", "주문 취소"),
    (r"^교환\|반품\|환불", "교환/반품"),         # 문장 단어로 교환 / 반품·환불을 나눔
    (r"^배송_", "배송"),
    (r"^결제_", "결제"),
    (r"^제품_", "상품"),
    (r"^멤버십_", "쿠폰·적립금·회원"),
    # 쇼핑몰 행사·이벤트 할인은 원칙 4에 따라 쿠폰·적립금·회원 (카드사 행사는 아래 원칙 4 처리에서 결제로 바뀜)
    # 혜택 단어(쿠폰·적립·할인 등)가 없는 "1+1 구성품이 뭐예요?" 같은 문장은 TEXT_EVIDENCE에서 걸러짐
    (r"^행사_", "쿠폰·적립금·회원"),
    (r"^웹사이트_", "기타"),                     # 로그인·회원가입 문장은 쿠폰·적립금·회원으로
]

MEMBER_WORDS = r"로그인|아이디|비밀번호|회원|가입|적립|포인트|쿠폰"
WEB_WORDS = r"홈페이지|사이트|웹|앱|어플|페이지|화면|접속|오류|에러|게시판|링크|검색"
# 웹사이트 문의라도 이 유형들의 근거 단어가 있으면 버림.
# ("택배사 사이트에 송장 조회가 안 돼요"는 배송 문의인데 '기타'로 배우면 모델이 사이트 단어만 보고 기타로 오분류함)
NOT_OTHER = ["배송", "결제", "교환", "반품·환불", "주문 취소"]

# 원칙 4 (docs/labeling_guide.md): 할인은 누가 주는 혜택인지로 정한다.
# 4번의 '결제_할인_질문'에는 쇼핑몰 쿠폰·포인트 문의가 섞여 있어 그대로 결제로 옮기면 가이드와 어긋남.
#   쇼핑몰 혜택 단어만 있음 → 쿠폰·적립금·회원 / 카드사·결제수단 단어만 있음 → 결제 / 둘 다 → 애매해서 버림
MALL_BENEFIT_QA = r"쿠폰|적립|포인트|등급|(?<!비)회원|멤버십"   # '비회원 결제'는 결제 문의라 제외
# 다른 유형이 섞인 문장을 거르는 단어 (해당 유형 자신은 제외하고 검사)
CROSS_WORDS = {"교환": "교환", "반품·환불": r"반품|환불", "주문 취소": "취소"}

# 4번 n(부정) 중에서 불만을 '드러내는' 문장만 부정으로 사용 (docs/labeling_guide.md 3장 기준)
NEG_EVIDENCE = (
    r"왜|도대체|도데체|아직|너무|계속|몇 ?번|언제까지|며칠|일주일|[0-9]+ ?주|사기|황당|어이|짜증|화가|화나|"
    r"실망|불친절|엉뚱|최악|답답|말이 안|이게 뭐|뭡니까|건가요\?|거 아닙니까|한 거 아니|"
    r"했는데.{0,15}(안 ?|없|못)"
)
# 4번 m(중립) 중 강한 불만 단어가 있으면 라벨이 의심스러워 버림
STRONG_NEG = r"도대체|도데체|사기|황당|어이없|짜증|최악|화가|화나|불친절"


def resolve(path: str) -> Path:
    path = Path(path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def map_category(intent: str, text: str):
    for pattern, category in INTENT_RULES:
        if re.search(pattern, intent):
            break
    else:
        return None
    if category is None:
        return None
    if category == "교환/반품":
        has_ex, has_ret = "교환" in text, bool(re.search(r"반품|환불", text))
        if has_ex == has_ret:  # 둘 다 있거나 둘 다 없으면 애매
            return None
        category = "교환" if has_ex else "반품·환불"
    elif category == "기타":
        if re.search(MEMBER_WORDS, text):
            category = "쿠폰·적립금·회원"
        elif not re.search(WEB_WORDS, text) or any(re.search(TEXT_EVIDENCE[c], text) for c in NOT_OTHER):
            return None
        else:
            return "기타"
    if category in ("결제", "쿠폰·적립금·회원"):
        has_card, has_mall = bool(re.search(CARD_BENEFIT, text)), bool(re.search(MALL_BENEFIT_QA, text))
        if has_card and has_mall:
            return None
        # 행사 문장의 '카드'는 메모리카드·그래픽카드 증정 같은 상품인 경우가 많아 결제로 바꾸지 않고 버림
        if intent.startswith("행사_") and has_card:
            return None
        if category == "결제" and has_mall:
            category = "쿠폰·적립금·회원"
        elif category == "쿠폰·적립금·회원" and has_card:
            category = "결제"
    if not re.search(TEXT_EVIDENCE[category], text):
        return None
    for other, words in CROSS_WORDS.items():
        if other != category and re.search(words, text):
            return None
    return category


def map_sentiment(label: str, text: str):
    if label == "n":
        return "부정" if re.search(NEG_EVIDENCE, text) else None
    if label == "m":
        return None if re.search(STRONG_NEG, text) else "중립"
    return None  # p는 대부분 단순 질문이라 사용 안 함


def load_qa(split: str) -> pd.DataFrame:
    files = sorted(glob.glob(str(QA_SOURCE / ("Training" if split == "train" else "Validation") / "*" / "*.csv")))
    usecols = ["발화자", "발화문", "카테고리", "감성", "인텐트", "상담번호"]
    df = pd.concat(pd.read_csv(f, encoding="utf-8-sig", usecols=usecols, dtype=str) for f in files)
    df = df[(df["발화자"] == "c") & ~df["카테고리"].isin(OFFLINE_DOMAINS)].dropna(subset=["발화문", "인텐트"])
    df["text"] = df["발화문"].map(lambda t: " ".join(str(t).split()))
    df = df[df["text"].str.replace(" ", "", regex=False).str.len() >= MIN_TEXT_LENGTH]
    df = df[df["text"].str.len() <= 150].drop_duplicates(subset="text")
    df["category"] = [map_category(i, t) for i, t in zip(df["인텐트"], df["text"])]
    df["sentiment"] = [map_sentiment(s, t) for s, t in zip(df["감성"], df["text"])]
    return pd.DataFrame({
        "text": df["text"], "category": df["category"], "sentiment": df["sentiment"],
        "intent": df["인텐트"], "label_rule": "qa_intent", "source_category": df["카테고리"],
        "dialog_id": "qa_" + df["상담번호"].fillna("").astype(str), "source_split": "qa_" + split,
        "qa_sentiment": df["감성"],
    })


def load_dialog_negatives() -> pd.DataFrame:
    """2번 데이터(쇼핑)에서 사람이 '부정감정표현하기'로 표시한 고객 문장."""
    rows = []
    for f in glob.glob(str(DIALOG_SOURCE / "*" / "라벨링데이터" / "*L_1.shopping" / "*" / "*.json")):
        try:
            data = json.loads(Path(f).read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        for info in data["info"]:
            for line in info["annotations"]["lines"]:
                if line["speaker"]["id"] == "B" and line.get("speechAct", "").startswith("부정감정표현"):
                    text = re.sub(r"#@[^#]*#", "ㅇㅇ", line["norm_text"][2:])
                    text = " ".join(text.split())
                    if len(text.replace(" ", "")) >= MIN_TEXT_LENGTH:
                        rows.append({"text": text, "sentiment": "부정", "dialog_id": f"d2_{Path(f).stem}"})
    df = pd.DataFrame(rows).drop_duplicates(subset="text")
    return df.assign(category=None, intent="부정감정표현하기", label_rule="dialog_speech_act",
                     source_category="목적대화", source_split="dialog2")


def sample_per_category(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    return pd.concat(g.sample(min(len(g), n), random_state=seed) for _, g in df.groupby("category"))


def parse_args():
    p = argparse.ArgumentParser(description="4번·2번 데이터 정제")
    p.add_argument("--category-base", default="data/raw/inquiries.csv")
    p.add_argument("--sentiment-base", default="data/raw/inquiries_sentiment.csv")
    p.add_argument("--per-category", type=int, default=1500, help="유형별 4번 학습 문장 수")
    p.add_argument("--extra-negative", type=int, default=2500, help="감정 학습에 더할 4번 부정 문장 수")
    p.add_argument("--test-per-category", type=int, default=100, help="외부 테스트 유형별 문장 수")
    p.add_argument("--event-extra", type=int, default=500,
                   help="쿠폰·적립금·회원에 추가할 4번 '행사_*' 문장 수 (너무 많으면 쿠폰 유형이 할인 행사 위주로 바뀜)")
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if QA_SOURCE is None:
        raise SystemExit(f"4번 데이터 폴더를 찾을 수 없습니다: {DATASET_ROOT}")

    cat_base = pd.read_csv(resolve(args.category_base), encoding="utf-8-sig")
    sent_base = pd.read_csv(resolve(args.sentiment_base), encoding="utf-8-sig")
    test100 = pd.read_csv(resolve("data/test/real_inquiries_100.csv"), encoding="utf-8-sig")
    key = lambda s: s.astype(str).str.replace(" ", "", regex=False)
    seen = set(key(cat_base["text"])) | set(key(sent_base["text"])) | set(key(test100["text"]))

    print("[4번 데이터 읽는 중] 수백만 줄이라 1~2분 걸립니다.")
    train = load_qa("train")
    valid = load_qa("valid")
    train = train[~key(train["text"]).isin(seen)]
    valid = valid[~key(valid["text"]).isin(seen | set(key(train["text"])))]
    print(f"[4번] 학습용 후보 {len(train):,}건 / 테스트용 후보 {len(valid):,}건")
    print("  유형 매핑 결과 (학습용 후보):")
    print(train["category"].value_counts().reindex(CATEGORY_LABELS, fill_value=0).to_string())

    # 1) 유형 학습용
    # 행사 문장은 유형별 샘플과 따로 일정 수만 추가하고, 외부 테스트에는 넣지 않음 (기존 테스트와 비교 가능하게)
    is_event = lambda d: d["intent"].str.startswith("행사_")
    labeled = train.dropna(subset=["category"])
    events = labeled[is_event(labeled)]
    events = events.sample(min(len(events), args.event_extra), random_state=args.seed)
    qa_cat = pd.concat([sample_per_category(labeled[~is_event(labeled)], args.per_category, args.seed), events])
    print(f"  행사 문장 추가: {len(events)}건 {events['category'].value_counts().to_dict()}")
    valid = valid[~is_event(valid)]
    qa_cat.drop(columns="qa_sentiment").to_csv(resolve("data/raw/qa_category.csv"), index=False, encoding="utf-8-sig")
    cat_cols = list(cat_base.columns)
    with_qa = pd.concat([cat_base, qa_cat[cat_cols]]).sample(frac=1, random_state=args.seed)
    with_qa.to_csv(resolve("data/raw/inquiries_with_qa.csv"), index=False, encoding="utf-8-sig")

    # 2) 감정 학습용: 기존 + 유형 샘플(대부분 중립) + 4번 부정 추가 + 2번 부정
    extra_neg = train[(train["sentiment"] == "부정") & ~train.index.isin(qa_cat.index)]
    extra_neg = extra_neg[~extra_neg["text"].isin(qa_cat["text"])]
    extra_neg = extra_neg.sample(min(len(extra_neg), args.extra_negative), random_state=args.seed)
    dialog_neg = load_dialog_negatives()
    dialog_neg = dialog_neg[~key(dialog_neg["text"]).isin(seen)]
    sent_add = pd.concat([qa_cat.dropna(subset=["sentiment"]), extra_neg, dialog_neg])
    sent_add["sentiment_rule"] = sent_add["sentiment"]
    sent_add["sentiment_source"] = sent_add["source_split"].map(lambda s: "dialog2" if s == "dialog2" else "qa")
    sent_with_qa = pd.concat([sent_base, sent_add[[c for c in sent_base.columns if c in sent_add.columns]]])
    sent_with_qa = sent_with_qa.sample(frac=1, random_state=args.seed)
    sent_with_qa.to_csv(resolve("data/raw/inquiries_sentiment_with_qa.csv"), index=False, encoding="utf-8-sig")

    # 3) 외부 테스트: 유형이 정해진 문장에서 유형별로 뽑고, 감정은 정해진 경우만 사용
    test = sample_per_category(valid.dropna(subset=["category", "sentiment"]), args.test_per_category, args.seed)
    test = pd.DataFrame({"text": test["text"], "category": test["category"], "sentiment": test["sentiment"],
                         "difficulty": "외부", "note": test["intent"] + " / " + test["source_category"]})
    test = test.sample(frac=1, random_state=args.seed)
    test.to_csv(resolve("data/test/external_test.csv"), index=False, encoding="utf-8-sig")

    print(f"\n[유형 학습] 4번 {len(qa_cat):,}건 추가 → {resolve('data/raw/inquiries_with_qa.csv').name} ({len(with_qa):,}건)")
    print(qa_cat["category"].value_counts().reindex(CATEGORY_LABELS, fill_value=0).to_string())
    print(f"\n[감정 학습] 4번 {len(sent_add) - len(dialog_neg):,}건 (부정 추가 {len(extra_neg):,}) + 2번 부정 {len(dialog_neg):,}건"
          f" → {len(sent_with_qa):,}건")
    print(sent_with_qa["sentiment"].value_counts().to_string())
    print(f"\n[외부 테스트] {len(test):,}건")
    print(test["category"].value_counts().reindex(CATEGORY_LABELS, fill_value=0).to_string())
    print(test["sentiment"].value_counts().to_string())


if __name__ == "__main__":
    main()
