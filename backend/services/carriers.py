"""택배사 정보와 담당 기사 조회 (상담원이 택배사에 배송 진행을 확인할 때, 주문 정보 카드).

- 택배사 고객센터 대표번호와 배송조회 바로가기 주소 (송장번호를 넣어 새 탭으로 엶).
  ※ 2026-11-25 기준: CJ대한통운 1588-1255 만 검색으로 확인. 나머지 번호와 조회 주소 형식은 각 택배사 홈페이지에서
    확인한 뒤 여기만 고치면 됨 (화면·API 모두 이 표를 씀). 시연 데이터의 송장번호는 가짜라 실제 조회 결과는 '없음'.
- 담당 기사: 실제 서비스에서는 택배사 배송조회 API가 '배송 출발' 단계에 기사 이름·연락처를 줌.
  시연에서는 그 API 대신 주문번호로 정해지는 가짜 기사를 돌려줌 (같은 주문은 늘 같은 기사).
  연락처는 상담원 화면에도 가운데를 가리고, 고객 답변·AI 초안에는 넣지 않음 (개인정보).
"""

import hashlib

from backend.database.models import Order

CARRIERS: dict[str, dict[str, str]] = {
    "CJ대한통운": {"phone": "1588-1255", "track": "https://trace.cjlogistics.com/next/tracking.html?wblNo={no}"},
    "롯데택배": {"phone": "1588-2121", "track": "https://www.lotteglogis.com/home/reservation/tracking/linkView?InvNo={no}"},
    "한진택배": {"phone": "1588-0011",
              "track": "https://www.hanjin.com/kor/CMS/DeliveryMgr/WaybillResult.do?mCode=MN038&schLang=KR&wblnumText2={no}"},
    "우체국택배": {"phone": "1588-1300", "track": "https://service.epost.go.kr/trace.RetrieveDomRigiTraceList.comm?sid1={no}"},
}

_SURNAMES = "김이박최정강조윤장임한오서신권황안송"
_GIVEN = ["민수", "지훈", "성호", "영철", "동현", "상우", "재원", "현우", "준호", "태영", "경수", "승민"]


def carrier_info(order: Order) -> dict | None:
    """택배사 대표번호와 이 송장의 배송조회 주소 (출고 전이거나 모르는 택배사면 None)"""
    c = CARRIERS.get(order.carrier or "")
    if c is None or not order.tracking_number:
        return None
    no = "".join(ch for ch in order.tracking_number if ch.isdigit())
    return {"name": order.carrier, "phone": c["phone"], "tracking_url": c["track"].format(no=no)}


def driver_info(order: Order) -> dict | None:
    """담당 기사 (택배사 조회 API 흉내): '배송 출발' 단계가 있어야 배정됨. 연락처는 가운데를 가림"""
    if not any(e.status == "배송 출발" for e in order.shipment_events):
        return None
    h = int(hashlib.sha256(order.order_number.encode()).hexdigest(), 16)
    name = _SURNAMES[h % len(_SURNAMES)] + _GIVEN[(h // 31) % len(_GIVEN)]
    return {"name": f"{name} 기사", "phone": f"010-****-{h % 10000:04d}"}
