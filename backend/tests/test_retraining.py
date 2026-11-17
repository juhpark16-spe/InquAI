"""재학습 준비: 추가 학습 데이터(train.py --extra-train)와 약점 보강 문장 걸러내기(generate_weak.py)."""

import sys
from argparse import Namespace
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))  # 학습 스크립트는 폴더 안에서 서로 import

import generate_weak  # noqa: E402
import train  # noqa: E402
from labels import CATEGORY_LABELS  # noqa: E402


def test_extra_train_goes_only_to_train_split(tmp_path):
    df = pd.DataFrame({"text": ["배송 언제 와요", "쿠폰 안 돼요"], "category": ["배송", "쿠폰·적립금·회원"]})
    train_df = df.iloc[:1]
    extra = tmp_path / "corr.csv"
    pd.DataFrame({"text": ["쿠폰 안 돼요", "하나만 빼 주세요"],          # 첫 문장은 이미 데이터에 있음
                  "category": ["쿠폰·적립금·회원", "주문 취소"]}).to_csv(extra, index=False)

    out, info = train.add_extra_train(train_df, df, Namespace(extra_train=[str(extra)], extra_repeat=[3]),
                                      "category", CATEGORY_LABELS)

    assert info == [{"file": str(extra), "rows": 1, "repeat": 3}]
    assert out["text"].tolist() == ["배송 언제 와요"] + ["하나만 빼 주세요"] * 3


def test_generate_weak_filters():
    rows = pd.DataFrame([
        {"text": "3개 세트인데 2개만 들어 있어요 나머지는 어떻게 되나요", "subtype": "누락"},
        {"text": "3개 세트인데 2개만 와서 반품하고 싶어요", "subtype": "누락"},            # 요청이 반품 → 원칙 1
        {"text": "받는 사람 이름을 [새이름]으로 바꿔 주세요 아직 안 나갔죠", "subtype": "받는 사람·배송지 변경"},
        {"text": "이름을 바꾸고 싶어요 어디서 하나요", "subtype": "회원 정보 변경"},          # 회원 단서 없음
        {"text": generate_weak.REVIEWED_OUT[0][0], "subtype": "바꿔 말한 취소"},
        {"text": "주문한 것과 전혀 다른 상품이 왔어요!", "subtype": "오배송"},              # 평가 세트 문장
    ])
    out = generate_weak.filter_rows(rows)
    reasons = out["reason"].tolist()

    assert pd.isna(reasons[0])
    assert reasons[1] == "다른 유형 단어"
    assert pd.isna(reasons[2]) and "ㅇㅇㅇ" in out["text"][2]
    assert reasons[3] == "단서 단어 없음"
    assert reasons[4].startswith("사람 검토")
    assert reasons[5] in ("기존 데이터와 겹침", "평가 문장과 비슷함")


def test_weak_subtypes_are_known_categories():
    assert {s[1] for s in generate_weak.SUBTYPES} <= set(CATEGORY_LABELS)
