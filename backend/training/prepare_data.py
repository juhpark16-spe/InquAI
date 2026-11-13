"""AI Hub「민원(콜센터) 질의-응답」K쇼핑 라벨링 데이터를 학습용 CSV로 정제합니다.

정제 순서
    1. K쇼핑 JSON 파일을 모두 읽습니다 (Training + Validation).
    2. 고객이 한 질문(화자=고객, 고객질문(요청) 있음)만 남깁니다.
    3. 너무 짧은 문장, 유형과 상관없는 의도(인사, 대기 요청 등)는 버립니다.
    4. 파일 이름이 아니라 문장마다 붙은 '고객의도'로 기획서의 8개 유형을 정합니다.
       (예: 「배송」 파일에도 새 주문 문의가 많이 섞여 있기 때문)
       문장 안에 그 유형의 단서 단어가 없으면 맥락 없이는 이해할 수 없는 문장으로 보고 버립니다.
       고객의도만으로 틀리는 경우는 문장 내용으로 보정합니다 (docs/labeling_guide.md 원칙 1·2·4).
    5. 같은 문장은 하나만 남기고, 유형별 최대 개수를 맞춥니다.
    6. 감정은 고객의도에 '불만', '항의' 등이 있으면 부정, 나머지는 중립으로 임시로 붙입니다.
    7. 직접 작성한 웹 문의 보충 데이터(data/supplement/web_inquiries.csv)를 합칩니다.

실행 예시 (프로젝트 루트에서)
    python backend/training/prepare_data.py
    python backend/training/prepare_data.py --max-per-category 3000
    python backend/training/prepare_data.py --source-dir "D:/dataset/01.데이터"

결과
    data/raw/inquiries.csv            학습용 데이터 (text, category, sentiment, ...) → train.py 입력
    data/raw/inquiries_intent_map.csv 고객의도 → 유형 변환표 (규칙 검토용, 버려진 의도 포함)
"""

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

from labels import CATEGORY_LABELS

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT_ROOT.parent / "dataset" / "1.문의유형_민원(콜센터) 질의-응답 데이터" / "01.데이터"

DROP = None  # 유형을 정할 수 없어 버리는 문장

# ---------------------------------------------------------------------------
# 규칙 1. 버리는 의도: 유형과 상관없는 대화 진행용 발화
# ---------------------------------------------------------------------------
EXCLUDE_PATTERNS = [
    r"상담사", r"대기", r"인사", r"재연락", r"통화", r"연락사유", r"성명", r"고객정보",
    r"전화번호", r"연락처", r"안내내용", r"감사",
    r"^문의사항$", r"^고객문의$", r"^문의요청$", r"^문의$",
    r"^고객불만", r"^불만",  # 무엇에 대한 불만인지 의도에 없음
    r"안내$",                # 상담사 안내를 따라 말한 문장 ("지금은 품절이에요")
]

# 규칙 2. 애매해서 버리는 의도
AMBIGUOUS_PATTERNS = [
    r"교환.*반품|반품.*교환",            # 교환인지 반품인지 알 수 없음
    r"(사이즈|색상|주문|구매상품)변경",  # 출고 전 주문 변경인지 교환인지 알 수 없음
]

# 규칙 3. 고객의도 → 유형. 위에서부터 차례로 검사하고 처음 맞는 유형을 씁니다.
#   순서가 중요합니다. 예) "카드취소문의"는 '취소'보다 '카드'를 먼저 검사해 결제로 분류
CATEGORY_RULES = [
    ("교환", r"교환"),
    ("반품·환불", r"반품|환불|수거|회수"),
    ("결제", r"결제|카드|할부|일시불|무통장|입금|계좌|영수증|청구할인"),
    ("주문 취소", r"취소|출고중지"),
    ("쿠폰·적립금·회원", r"쿠폰|적립|포인트|회원|비밀번호|아이디|로그인|할인|마일리지|등급"),
    ("배송", r"배송|택배|송장|출고|도착|주소|배달"),
    ("상품", r"사이즈|색상|가격|구성|재고|품절|하자|불량|품질|AS|에이에스|사용법|사용방법"
             r"|소재|용량|원산지|제품|상품정보|상품문의|상품설명|방송상품문의"),
    # 홈쇼핑 특성상 많은 '새 주문' 문의는 8개 유형 어디에도 속하지 않으므로 기타로 분류
    ("기타", r"방송상품주문|상품주문|추가주문|자동주문|^주문(요청|신청|문의|방법|가능|절차)"),
]

# 규칙 4. 문장 자체에 유형의 단서가 있어야 남깁니다.
#   콜센터 대화 중간 문장은 앞뒤 맥락이 없으면 뜻을 알 수 없는 경우가 많습니다.
#   예) 의도는 '교환사이즈요청'인데 문장은 "백십으로 그냥 해주세요" → 웹 문의 폼에는 이런 글이 오지 않음
TEXT_EVIDENCE = {
    "배송": r"배송|택배|도착|언제 ?와|언제 ?오|안 ?와|안 ?오|주소|송장|출고|발송|보내|배달|받을 수",
    "주문 취소": r"취소",
    "교환": r"교환|바꿔|바꾸|바꿀",
    "반품·환불": r"반품|환불|돌려|회수|수거|가져가|반송",
    "결제": r"결제|카드|할부|일시불|입금|계좌|무통장|영수증|금액|[천만백]\s?원|원이",
    "상품": r"사이즈|색상|색깔|컬러|가격|재고|품절|불량|하자|고장|작아|커서|소재|용량|제품|상품|에이에스|AS|사용",
    "쿠폰·적립금·회원": r"쿠폰|적립|포인트|회원|비밀번호|아이디|로그인|할인|가입|마일리지",
    "기타": r"주문|방송|신청|사려|구매|구입",
}

# 감정 규칙 (임시): 고객의도에 이런 단어가 있으면 부정
NEGATIVE_PATTERN = r"불만|항의|불편|짜증|분노|실망"
POSITIVE_PATTERN = r"만족|칭찬"

MIN_TEXT_LENGTH = 8  # 공백을 뺀 글자 수가 이보다 적으면 버림 ("네 알겠습니다" 등)


def intent_to_category(intent: str):
    if not intent:
        return DROP
    if any(re.search(p, intent) for p in EXCLUDE_PATTERNS):
        return DROP
    if any(re.search(p, intent) for p in AMBIGUOUS_PATTERNS):
        return DROP
    for category, pattern in CATEGORY_RULES:
        if re.search(pattern, intent):
            return category
    return DROP


# ---------------------------------------------------------------------------
# 규칙 5. 문장 내용으로 라벨 보정 (docs/labeling_guide.md의 원칙)
#   고객의도 이름만 보면 틀리는 경우를 문장 내용으로 바로잡습니다.
# ---------------------------------------------------------------------------
CARD_BENEFIT = r"카드|청구|무이자|할부|일시불|페이"          # 카드사·결제 수단 혜택
MALL_BENEFIT = r"쿠폰|적립|포인트|자동\s?주문|등급|회원"       # 쇼핑몰 혜택
EXCHANGE_WORD = r"교환"
EXCHANGE_REQUEST = r"교환|바꿔\s?주|바꾸려|바꿀래|바꾸고"   # 상품 문장용: "삼십으로 바꾸고 싶어요"
RETURN_REQUEST = r"반품|환불"
PICKUP = r"회수|수거|가져가"


def correct_category(category: str, intent: str, text: str):
    """(보정된 유형, 적용한 원칙 이름)을 돌려줍니다. 보정이 없으면 원칙 이름은 빈 문자열."""
    has_return = re.search(RETURN_REQUEST, text) is not None
    # 배송 문장의 '바꿔 주세요'는 대부분 배송지 변경이므로 '교환'이라는 단어만 인정
    exchange_pattern = EXCHANGE_WORD if category == "배송" else EXCHANGE_REQUEST
    has_exchange = re.search(exchange_pattern, text) is not None

    # 원칙 4: 의도는 '할인'인데 카드사 혜택 이야기면 결제
    if (category == "쿠폰·적립금·회원" and "할인" in intent
            and re.search(CARD_BENEFIT, text) and not re.search(MALL_BENEFIT, text)):
        return "결제", "원칙4_카드사할인"

    # 원칙 1: 사이즈·불량 불만(상품)인데 문장에서 교환이나 반품을 요청하면 그 요청 유형
    if category == "상품" and has_exchange != has_return:
        return ("교환", "원칙1_교환요청") if has_exchange else ("반품·환불", "원칙1_반품요청")

    # 원칙 2·5: 배송 의도인데 교환·반품 과정 이야기면 그 처리 유형, 둘 다 없이 회수만 있으면 판단 불가
    if category == "배송":
        if has_exchange != has_return:
            return ("교환", "원칙2_교환과정") if has_exchange else ("반품·환불", "원칙2_반품과정")
        if not has_exchange and re.search(PICKUP, text):
            return DROP, "원칙9_판단불가"

    return category, ""


def intent_to_sentiment(intent: str) -> str:
    if re.search(NEGATIVE_PATTERN, intent):
        return "부정"
    if re.search(POSITIVE_PATTERN, intent):
        return "긍정"
    return "중립"


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    # 문장 앞의 맞장구 제거: "네, 아 저기 반품하려고요" → "반품하려고요"
    # 뒤에 공백·문장부호가 있을 때만 지움 ("아니요", "아직"의 '아'는 그대로 둠)
    text = re.sub(r"^((네|예|아|어|음|저기요?)[\s,.~]+)+", "", text).strip()
    return text


def parse_args():
    p = argparse.ArgumentParser(description="K쇼핑 콜센터 데이터 정제")
    p.add_argument("--source-dir", default=str(DEFAULT_SOURCE), help="AI Hub '01.데이터' 폴더")
    p.add_argument("--output", default="data/raw/inquiries.csv")
    p.add_argument("--max-per-category", type=int, default=2000, help="유형별 최대 문장 수 (0이면 제한 없음)")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--no-text-evidence", action="store_true", help="규칙 4(문장 단서 확인)를 끔")
    p.add_argument("--supplement", nargs="*",
                   default=["data/supplement/web_inquiries.csv", "data/supplement/generated_other.csv"],
                   help="보충 데이터 파일들 (text,category,sentiment). 아무것도 안 주면 사용 안 함")
    return p.parse_args()


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 콘솔에서 한글 깨짐 방지
    args = parse_args()
    source_dir = Path(args.source_dir)
    output = Path(args.output)
    if not output.is_absolute():
        output = PROJECT_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(source_dir.rglob("*K쇼핑*.json"))
    if not files:
        raise FileNotFoundError(f"K쇼핑 JSON 파일이 없습니다: {source_dir}\n압축(zip)을 먼저 풀어 주세요.")

    # 1~4. 읽기, 고객 질문만, 짧은 문장 제거, 유형 정하기
    rows = []
    intent_stats = Counter()   # (고객의도, 유형) → 문장 수
    dropped = Counter()
    corrections = Counter()    # 규칙 5로 라벨을 바꾼 횟수
    for f in files:
        split = "Validation" if "Validation" in f.name else "Training"
        data = json.loads(f.read_text(encoding="utf-8"))
        print(f"[읽기] {f.name}: {len(data):,}행")
        for r in data:
            if r.get("화자") != "고객":
                continue
            text = clean_text(r.get("고객질문(요청)", ""))
            if not text:
                continue
            intent = r.get("고객의도", "").strip()
            category = intent_to_category(intent)
            intent_stats[(intent, category or "(버림)")] += 1
            if category is DROP:
                dropped["유형 없음/애매함"] += 1
                continue
            if len(text.replace(" ", "")) < MIN_TEXT_LENGTH:
                dropped["너무 짧음"] += 1
                continue
            category, rule = correct_category(category, intent, text)
            if rule:
                corrections[rule] += 1
            if category is DROP:
                dropped["보정 후 판단 불가"] += 1
                continue
            if not args.no_text_evidence and not re.search(TEXT_EVIDENCE[category], text):
                dropped["문장에 유형 단서 없음"] += 1
                continue
            rows.append({
                "text": text,
                "category": category,
                "sentiment": intent_to_sentiment(intent),
                "intent": intent,
                "label_rule": rule,
                "source_category": r.get("카테고리", ""),
                "dialog_id": r.get("대화셋일련번호", ""),
                "source_split": split,
            })

    df = pd.DataFrame(rows)
    assert set(df["category"]) <= set(CATEGORY_LABELS), "labels.py에 없는 유형이 있습니다"

    # 5. 중복 제거 (공백만 다른 문장도 같은 문장으로 봄)
    before = len(df)
    df["_key"] = df["text"].str.replace(" ", "", regex=False)
    df = df.drop_duplicates(subset="_key").drop(columns="_key")
    dropped["중복"] = before - len(df)

    print("\n[유형별 문장 수 (개수 맞추기 전)]")
    print(df["category"].value_counts().reindex(CATEGORY_LABELS, fill_value=0).to_string())

    # 5. 유형별 최대 개수 맞추기 (부정 문장은 귀하므로 먼저 남기고 나머지를 무작위로 채움)
    if args.max_per_category > 0:
        random.seed(args.seed)
        parts = []
        for category, group in df.groupby("category"):
            if len(group) <= args.max_per_category:
                parts.append(group)
                continue
            neg = group[group["sentiment"] == "부정"]
            rest = group[group["sentiment"] != "부정"]
            n_neg = min(len(neg), args.max_per_category // 2)
            picked = pd.concat([
                neg.sample(n=n_neg, random_state=args.seed),
                rest.sample(n=args.max_per_category - n_neg, random_state=args.seed),
            ])
            parts.append(picked)
        df = pd.concat(parts).sample(frac=1, random_state=args.seed).reset_index(drop=True)

    # 6. 직접 작성한 웹 문의 보충 데이터 합치기 (개수 제한 없이 전부 사용)
    #    콜센터 데이터의 '기타'는 대부분 홈쇼핑 새 주문이라, 입점·개인정보·앱 오류 같은
    #    실제 웹 문의를 보충하지 않으면 모델이 진짜 기타 문의를 전혀 맞히지 못합니다.
    #    generated_*.csv는 LLM이 생성한 문장(generate_other.py)이라 출처를 따로 표시합니다.
    #    source_split이 'generated'이면 label_sentiment.py가 감정을 LLM 기준으로 다시 붙입니다
    #    (사람이 붙인 'supplement' 라벨만 그대로 유지).
    for supplement in args.supplement or []:
        supplement = Path(supplement)
        if not supplement.is_absolute():
            supplement = PROJECT_ROOT / supplement
        if not supplement.exists():
            print(f"\n[보충] {supplement.name}: 파일이 없어 건너뜀")
            continue
        generated = supplement.stem.startswith("generated")
        sup = pd.read_csv(supplement, encoding="utf-8-sig")
        unknown = set(sup["category"]) - set(CATEGORY_LABELS)
        if unknown:
            raise ValueError(f"보충 데이터에 labels.py에 없는 유형이 있습니다: {unknown}")
        sup["text"] = sup["text"].astype(str).str.strip()
        sup["intent"] = sup["subtype"] if generated and "subtype" in sup else ""
        sup["label_rule"] = ""
        sup["source_category"] = "생성" if generated else "보충"
        sup["dialog_id"] = ""
        sup["source_split"] = "generated" if generated else "supplement"
        existing = set(df["text"].str.replace(" ", "", regex=False))
        sup = sup[~sup["text"].str.replace(" ", "", regex=False).isin(existing)]
        df = pd.concat([df, sup[df.columns]]).sample(frac=1, random_state=args.seed).reset_index(drop=True)
        print(f"\n[보충] {supplement.name}: {len(sup)}건 추가")
        print(sup["category"].value_counts().reindex(CATEGORY_LABELS, fill_value=0).to_string())

    # 저장
    df.to_csv(output, index=False, encoding="utf-8-sig")
    map_path = output.with_name(output.stem + "_intent_map.csv")
    pd.DataFrame(
        [{"intent": i, "category": c, "count": n} for (i, c), n in intent_stats.most_common()]
    ).to_csv(map_path, index=False, encoding="utf-8-sig")

    print(f"\n[라벨 보정] {dict(corrections)}  (규칙 5, docs/labeling_guide.md)")
    print(f"[버린 문장] {dict(dropped)}")
    print("\n[최종 유형별 문장 수]")
    print(df["category"].value_counts().reindex(CATEGORY_LABELS, fill_value=0).to_string())
    print("\n[최종 감정 분포]")
    print(df["sentiment"].value_counts().to_string())
    print(f"\n[저장] 학습 데이터: {output} ({len(df):,}건)")
    print(f"[저장] 의도 변환표: {map_path}")


if __name__ == "__main__":
    main()
