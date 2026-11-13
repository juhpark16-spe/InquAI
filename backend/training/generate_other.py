"""OpenAI LLM으로 '기타' 유형 고객 문의를 생성합니다.

왜 필요한가
    학습 데이터의 '기타'는 대부분 콜센터의 홈쇼핑 새 주문 문장이라, 실제 웹 서비스의 기타 문의
    (입점·제휴, 앱 오류, 알림 설정, 개인정보, 서비스 불만 등)가 거의 없습니다. 공개 데이터도 없어서 생성합니다.

하는 일
    1. docs/labeling_guide.md의 기타 정의(1장, 원칙 7·8)를 하위 유형 12개로 나누고(SUBTYPES),
       말투 3가지(STYLES)마다 문장을 생성합니다. 감정(긍정·중립·부정)도 함께 받습니다.
    2. 다른 유형의 근거 단어(배송·결제·교환·반품·취소·쿠폰·로그인 등)가 있는 문장, 너무 짧은 문장,
       기존 학습·테스트 데이터와 겹치는 문장은 버립니다.

결과
    data/supplement/generated_other.csv   text, category(기타), sentiment, subtype, style
    → prepare_data.py가 web_inquiries.csv와 함께 보충 데이터로 합칩니다.
    생성 문장은 꼭 일부를 사람이 읽어 보고, 이상한 문장은 지운 뒤 학습에 쓰세요.

실행 예시 (프로젝트 루트에서)
    python backend/training/generate_other.py --per-request 25
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

from labels import SENTIMENT_LABELS
from prepare_data import MIN_TEXT_LENGTH, TEXT_EVIDENCE

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# (하위 유형, 설명, 예시) — docs/labeling_guide.md 1장·원칙 7·8의 기타
SUBTYPES = [
    ("새 주문 방법", "전화·방송·대량·단체 주문 방법, 법인 구매, 해외에서 주문 가능 여부",
     "방송 보고 전화로 주문하고 싶은데 번호가 뭐예요?"),
    ("입점·제휴", "판매자 입점, 브랜드 제휴, 광고·협찬·인플루언서 제안, 물류·B2B 제안",
     "저희 브랜드 입점하고 싶은데 절차가 어떻게 되나요?"),
    ("고객센터 이용", "운영 시간, 상담원 연결, 채팅·이메일 상담 채널, 장애인·외국인 상담 지원",
     "주말에도 상담 가능한가요?"),
    ("개인정보", "개인정보 처리방침, 수집 항목, 열람·삭제 요청, 제3자 제공 동의 철회, 유출 우려 (회원정보 수정은 제외)",
     "제 개인정보가 어디까지 제공되는지 알고 싶어요."),
    ("앱·웹 오류", "앱이 튕김·멈춤, 화면 깨짐, 검색 안 됨, 페이지 로딩 안 됨, 업데이트 후 오류 (로그인·결제창 오류는 제외)",
     "앱 업데이트하고 나서 자꾸 꺼져요."),
    ("알림 설정", "마케팅 문자·이메일·푸시 수신 거부, 알림이 너무 많음, 광고 전화",
     "광고 문자 그만 받고 싶어요."),
    ("부가 서비스", "선물 포장, 메시지 카드, 각인 서비스, 매장 보관 서비스, 기업 선물 세트 안내",
     "선물 포장 서비스가 있나요?"),
    ("게시판·리뷰", "리뷰 작성·수정·삭제, 문의글 답변 확인, 게시글 신고, 사진 리뷰 업로드 오류",
     "예전에 쓴 리뷰를 지우고 싶어요."),
    ("서비스 불만", "상담원 불친절, 응대 지연, 같은 설명 반복, 답변 없음, 담당자 변경 요구 (특정 주문 처리 불만은 제외)",
     "문의 남긴 지 사흘째인데 답이 없네요."),
    ("칭찬·건의", "대상이 정해지지 않은 일반 칭찬·감사, 서비스 개선 건의, 기능 추가 제안",
     "항상 잘 이용하고 있어요. 다크모드도 생기면 좋겠어요."),
    ("회사·매장 정보", "본사 주소, 오프라인 매장 위치·영업시간·주차, 채용, 회사 소식",
     "오프라인 매장은 어디에 있나요?"),
    ("이벤트 참여", "경품 이벤트 응모 방법, 당첨자 발표, 경품 수령 방법, 체험단 신청 (할인·쿠폰·적립 혜택은 제외)",
     "체험단 신청은 어떻게 하나요?"),
]

STYLES = [
    ("채팅체", "쇼핑몰 1:1 채팅에 짧게 쓰는 구어체. 존댓말·반말 섞임, 10~40자 위주"),
    ("게시판체", "고객 문의 게시판에 정중하게 쓰는 글. 상황 설명이 한두 문장 붙음, 20~90자"),
    ("엉성한 글", "휴대폰으로 급하게 친 글. 띄어쓰기를 군데군데 빼먹고(전부 붙이지는 않음), 맞춤법이 조금 틀리고, "
                 "'ㅠㅠ' 'ㅋ' 같은 표현이나 물음표 생략이 가끔 있음"),
]

# 다른 유형으로 읽힐 수 있는 단어. 기타 문장에 있으면 버림 (원칙 7)
OTHER_CATEGORY_WORDS = [TEXT_EVIDENCE[c] for c in ["배송", "주문 취소", "교환", "반품·환불", "결제", "쿠폰·적립금·회원"]]
# 상품 유형으로 읽힐 수 있는 단어 ("사진이 실물과 달라요"는 상품 문의). TEXT_EVIDENCE['상품']은 '사용'까지 있어 너무 넓음
PRODUCT_WORDS = r"상품|제품|실물|사이즈|색상|가격|재고|품절|불량|하자|옵션|소재"
# 문장 끝에 따로 붙은 인사말. LLM이 습관처럼 붙여 35%가 이렇게 끝났음 (기존 데이터는 0.5%)
# → 그대로 두면 모델이 "끝이 '감사합니다'면 기타"로 잘못 배우므로 떼어냄
TAIL_GREETING = re.compile(r"(?<=[?.!요다죠까])[\s,.]*(감사합니다|감사드립니다|고맙습니다|부탁드립니다|부탁드려요|부탁해요)[.!~]*$")


POLITE_END = r"(?:감사합니다|감사드립니다|고맙습니다|부탁드립니다|부탁드려요)[.!~]*$"
MAX_POLITE_SHARE = 0.07


def clean_tail(text: str) -> str:
    return TAIL_GREETING.sub("", text).strip()

PROMPT = """너는 한국 온라인 쇼핑몰에 들어오는 고객 문의를 만드는 작가다.
아래 조건에 맞는 서로 다른 고객 문의 {n}개를 만든다.

[유형] 기타 - {subtype}: {desc}
[예시] {example}
[말투] {style}: {style_desc}

[규칙]
- 실제 고객이 쓴 것처럼 자연스럽게. 문장마다 상황·표현·길이를 다르게 한다. 예시 문장을 바꿔 쓰지 않는다.
- 아래 단어는 절대 쓰지 않는다 (다른 문의 유형으로 읽힘):
  배송, 택배, 도착, 송장, 출고, 발송, 취소, 교환, 반품, 환불, 결제, 카드, 입금, 계좌, 영수증, 쿠폰, 적립, 포인트, 회원, 로그인, 아이디, 비밀번호, 할인, 가입
- 이름·전화번호·주소를 꼭 써야 할 때만 실제 값 대신 'ㅇㅇ'으로 쓴다. 대부분의 문장에는 'ㅇㅇ'이 필요 없다.
- 감정을 함께 붙인다.
  부정: 불만·불편·실망을 드러냄 (짜증, 답답, 계속, 아직도, 왜 안 해 등)
  긍정: 감사·칭찬·만족이 분명함
  중립: 담담한 문의·요청. 형식적인 인사말만 있으면 중립
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


def generate(client, model, subtype, style, n, retries=3):
    name, desc, example = subtype
    style_name, style_desc = style
    content = PROMPT.format(n=n, subtype=name, desc=desc, example=example, style=style_name, style_desc=style_desc)
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": content}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "inquiries", "strict": True, "schema": SCHEMA}},
            )
            items = json.loads(resp.choices[0].message.content)["items"]
            return [{"text": " ".join(i["text"].split()), "sentiment": i["sentiment"],
                     "subtype": name, "style": style_name} for i in items]
        except Exception as e:  # 네트워크 오류, 사용량 제한 등
            print(f"  [재시도 {attempt + 1}/{retries}] {name}/{style_name}: {type(e).__name__}: {str(e)[:100]}")
    return []


def drop_reason(text: str):
    if len(text.replace(" ", "")) < MIN_TEXT_LENGTH:
        return "너무 짧음"
    for words in OTHER_CATEGORY_WORDS:
        if re.search(words, text):
            return "다른 유형 단어"
    if re.search(PRODUCT_WORDS, text):
        return "상품 단어"
    return None


def filter_rows(df: pd.DataFrame) -> pd.DataFrame:
    """끝 인사말 정리 → 다른 유형 단어·짧은 문장·중복·기존 데이터와 겹침 제거. reason 칸이 비어 있으면 사용."""
    df = df.copy()
    df["text"] = df["text"].map(clean_tail)
    df["reason"] = df["text"].map(drop_reason)
    key = lambda s: s.astype(str).str.replace(r"[\s.,!?~]", "", regex=True)
    existing = set()
    for f in ["data/raw/inquiries_with_qa.csv", "data/supplement/web_inquiries.csv",
              "data/test/real_inquiries_100.csv", "data/test/external_test.csv"]:
        if resolve(f).exists():
            existing |= set(key(pd.read_csv(resolve(f), encoding="utf-8-sig")["text"]))
    df.loc[df["reason"].isna() & key(df["text"]).isin(existing), "reason"] = "기존 데이터와 겹침"
    df.loc[df["reason"].isna() & key(df["text"]).duplicated(), "reason"] = "생성 문장끼리 중복"
    # "차단 부탁드립니다"처럼 떼어낼 수 없는 인사 끝맺음은 직접 쓴 보충 데이터 수준(약 7%)까지만 남김
    polite = df["reason"].isna() & df["text"].str.contains(POLITE_END)
    limit = int(MAX_POLITE_SHARE * (df["reason"].isna().sum() - polite.sum()) / (1 - MAX_POLITE_SHARE))
    excess = df[polite].sample(frac=1, random_state=0).index[limit:]
    df.loc[excess, "reason"] = "인사 끝맺음 과다"
    print(df["reason"].fillna("사용").value_counts().to_string())
    return df


def parse_args():
    p = argparse.ArgumentParser(description="기타 유형 문의 생성")
    p.add_argument("--output", default="data/supplement/generated_other.csv")
    p.add_argument("--model", default=None, help="기본값: .env의 OPENAI_MODEL, 없으면 gpt-5-mini")
    p.add_argument("--per-request", type=int, default=25, help="하위 유형·말투 조합마다 생성할 문장 수")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--refilter", action="store_true",
                   help="새로 생성하지 않고 --output 파일에 정리·걸러내기만 다시 적용 (API 비용 없음)")
    return p.parse_args()


def save(kept: pd.DataFrame, out: Path, seed: int):
    kept = kept[["text", "category", "sentiment", "subtype", "style"]].sample(frac=1, random_state=seed)
    kept.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n[하위 유형별]\n{kept['subtype'].value_counts().to_string()}")
    print(f"\n[감정]\n{kept['sentiment'].value_counts().to_string()}")
    print(f"\n[저장] {out} ({len(kept)}건) - 일부를 직접 읽어 보고 이상한 문장은 지워 주세요.")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    out = resolve(args.output)
    if args.refilter:
        df = pd.read_csv(out, encoding="utf-8-sig")
        print(f"[다시 걸러내기] {out.name} {len(df)}건")
        df = filter_rows(df)
        save(df[df["reason"].isna()].drop(columns="reason"), out, args.seed)
        return

    load_dotenv(PROJECT_ROOT / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY가 없습니다. .env 를 확인해 주세요.")
    model = args.model or os.getenv("OPENAI_MODEL") or "gpt-5-mini"
    client = OpenAI()

    jobs = [(s, st) for s in SUBTYPES for st in STYLES]
    print(f"[생성] 모델 {model} / 요청 {len(jobs)}회 × {args.per_request}문장")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = pool.map(lambda j: generate(client, model, j[0], j[1], args.per_request), jobs)
    df = pd.DataFrame([r for batch in results for r in batch])
    print(f"  생성 {len(df)}건")

    df = filter_rows(df)
    save(df[df["reason"].isna()].drop(columns="reason").assign(category="기타"), out, args.seed)


if __name__ == "__main__":
    main()
