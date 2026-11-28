"""긴급도 규칙: 분실 의심 (2026-11-27, 확장 세트 S005)"""

import pytest

from backend.ai.rules import get_urgency, is_lost_parcel


@pytest.mark.parametrize("text", [
    "택배 기사님은 배송완료라고 찍으셨는데 문 앞에 아무것도 없어요!! 분실된 것 같은데 빨리 찾아주시든지 조치해주세요 급해요!",
    "배송 완료라고 뜨는데 물건을 못 받았어요. 문 앞에도 경비실에도 없습니다.",
    "배송 완료로 떴는데 받은 게 없어요",
    "택배 기사님이 배송 완료 문자를 보냈는데 경비실에도 없고 택배함에도 없어요.",
    "어제 온 택배가 분실됐어요. 확인해 주세요.",
])
def test_lost_parcel_is_urgent(text):
    assert is_lost_parcel(text)
    assert get_urgency("배송", "중립", text) == "높음"


@pytest.mark.parametrize("text", [
    "지금 주문하면 보통 며칠 만에 받을 수 있어요?",
    "11월 10일에 주문한 패딩이 아직 안 왔어요. 지금 어디쯤 있나요?",
    "택배가 분실되면 어떻게 처리되나요?",
    "배송 완료 후 며칠 안에 반품 신청해야 하나요?",
])
def test_ordinary_shipping_question_is_not_lost(text):
    assert not is_lost_parcel(text)
    assert get_urgency("배송", "중립", text) == "낮음"


@pytest.mark.parametrize("text", [
    "ORD-2026-1042 하나 주문했는데 카드 결제 문자가 두 번 왔어요. 확인 부탁드립니다.",
    "같은 금액이 두 번 결제됐어요.",
    "중복 결제가 됐는데 하나 취소해 주세요.",
    "결제하다가 오류가 났는데 돈은 빠져나갔어요.",
])
def test_payment_error(text):
    from backend.ai.rules import is_payment_error
    assert is_payment_error(text)


@pytest.mark.parametrize("text", [
    "중복 결제는 어떻게 하나요?",   # 일반 질문 (일어난 일이 아님)
    "두 번 결제하면 무이자 할부가 되나요?",
    "현금영수증은 어떻게 발급받을 수 있나요?",
])
def test_not_payment_error(text):
    from backend.ai.rules import is_payment_error
    assert not is_payment_error(text)
