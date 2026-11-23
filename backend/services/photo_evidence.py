"""파손·불량·오배송 문의의 사진 (송장 1장 + 파손 부위 1장): 상담원이 "사진 보내 주세요"로 한 번 더 묻지 않게.

- 문의 화면의 '상품이 파손·불량이거나 잘못 왔어요' 체크: 제목·내용에 아래 표현이 보이면 자동으로 체크, 고객이 풀 수도 있음.
  체크되면 사진 칸을 두 칸으로 바꿈
- 두 칸(송장, 파손 부위)이 채워져야 등록. 단 '지금은 사진이 없어요'를 체크하면 사진 없이 등록 → photo_request = '나중에'
  (상자를 버렸거나 지금 찍을 수 없는 고객도 문의는 남길 수 있게). 추가 문의로 사진이 오면 '나중에'는 풀림
- 서버도 같은 규칙으로 확인 (화면을 거치지 않은 요청도). damage_report: 체크 그대로(true/false), 보내지 않으면 표현으로 판단.
  표현만으로는 일반 질문("파손되면 교환되나요?")도 걸릴 수 있어 고객이 체크를 풀 수 있게 함
- 사진 속에 정말 송장·파손이 찍혔는지는 보지 않음 (두 칸에 사진이 올라왔는지만)

DAMAGE_PATTERN 은 frontend/src/pages/customer/InquiryFormPage.tsx 의 DAMAGE_WORDS 와 같아야 함 (test_photo_evidence 에서 확인)
"""

import re

from backend.core.errors import AppError

DAMAGE_PATTERN = r"파손|깨(져|졌|짐|진)|찢(어|겨|긴|김)|불량|오배송|잘못\s?(왔|온|배송)|다른\s?(상품|제품|물건)이\s?(왔|배송)|흠집|스크래치|찌그러|구멍이|얼룩|변색"
DAMAGE_WORDS = re.compile(DAMAGE_PATTERN)
LABELS = ("송장", "파손 부위")   # 사진 칸 이름 (attachments.label)
LATER = "나중에"                  # inquiries.photo_request: 고객이 사진을 나중에 보내기로 함


def needs_photos(title: str, content: str, damage: bool | None = None) -> bool:
    """damage: 고객이 고른 '상품이 파손·불량이거나 잘못 왔어요' 체크 (None 이면 내용의 표현으로 판단,
    False 면 고객이 자동 체크를 풀었음 = 파손 문의 아님. 예: '파손되면 교환되나요?' 같은 일반 질문)"""
    if damage is not None:
        return damage
    return bool(DAMAGE_WORDS.search(f"{title} {content}"))


def check(title: str, content: str, tokens: list[str], labels: dict[str, str], later: bool, damage: bool | None = None) -> None:
    """등록 전에 확인: 파손 문의인데 두 칸이 없고 '나중에'도 아니면 422 (화면은 code 로 두 칸을 보여 줌)"""
    if any(t not in tokens for t in labels):
        raise AppError(422, "사진 정보가 맞지 않습니다. 사진을 다시 올려 주세요.", "INVALID_FILE")
    if not needs_photos(title, content, damage) or later:
        return
    missing = [name for name in LABELS if name not in labels.values()]
    if missing:
        raise AppError(422, f"파손·불량·오배송 문의는 {' · '.join(missing)} 사진이 필요해요. 지금 사진이 없으면 "
                            "'지금은 사진이 없어요'를 체크해 주세요.", "PHOTO_REQUIRED", missing=missing)
