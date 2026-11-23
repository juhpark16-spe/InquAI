"""파손·불량·오배송 문의의 사진 (송장 + 파손 부위), '지금은 사진이 없어요' 예외 (backend/services/photo_evidence.py)"""

from pathlib import Path

from sqlalchemy import select

from backend.agents.drafting import build_input
from backend.database.models import Attachment, Inquiry
from backend.services import photo_evidence
from backend.tests.test_customer_features import admin_login, upload
from backend.tests.test_inquiries import PW, ai, post  # noqa: F401  (ai 는 fixture)

DAMAGE = "받은 머그컵이 깨져서 왔어요. 교환해 주세요. (주문번호 20261110-0001)"


def token(client):
    return upload(client).json()["token"]


def test_damage_words_match_the_screen():
    """화면(InquiryFormPage.tsx)과 서버가 같은 표현으로 판단"""
    screen = (Path(__file__).resolve().parents[2] / "frontend/src/pages/customer/InquiryFormPage.tsx").read_text(encoding="utf-8")
    assert f"const DAMAGE_WORDS = /{photo_evidence.DAMAGE_PATTERN}/;" in screen
    for text in ("상품이 파손되어 왔어요", "유리가 깨졌어요", "다른 상품이 왔어요", "옷에 얼룩이 있어요", "오배송 같아요"):
        assert photo_evidence.needs_photos("문의", text), text
    for text in ("배송은 며칠 걸려요?", "사이즈 교환하고 싶어요", "쿠폰이 안 보여요"):
        assert not photo_evidence.needs_photos("문의", text), text


def test_damage_needs_two_photos_or_later(client, db, ai):
    r = post(client, DAMAGE)
    assert r.status_code == 422 and r.json()["code"] == "PHOTO_REQUIRED" and r.json()["missing"] == ["송장", "파손 부위"]

    one = token(client)
    r = post(client, DAMAGE, attachment_tokens=[one], photo_labels={one: "송장"})
    assert r.status_code == 422 and r.json()["missing"] == ["파손 부위"]

    a, b, extra = token(client), token(client), token(client)
    r = post(client, DAMAGE, attachment_tokens=[a, b, extra], photo_labels={a: "송장", b: "파손 부위"})
    assert r.status_code == 201
    labels = {x.token: x.label for x in db.scalars(select(Attachment).where(Attachment.inquiry_id.is_not(None)))}
    assert labels == {a: "송장", b: "파손 부위", extra: None}
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == r.json()["inquiry_number"]))
    assert inquiry.photo_request is None
    assert "[첨부 사진] 3장 (송장, 파손 부위)" in build_input(db, inquiry, [], None)

    assert post(client, "배송은 보통 며칠 걸려요?").status_code == 201          # 파손 문의가 아니면 사진 없어도 됨


def test_later_then_follow_up_photo(client, db, ai):
    r = post(client, DAMAGE, photos_later=True)
    assert r.status_code == 201
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == r.json()["inquiry_number"]))
    assert inquiry.photo_request == "나중에"
    assert "고객이 나중에 보내기로 함" in build_input(db, inquiry, [], None)          # AI 초안이 사진을 먼저 요청

    admin_login(client)
    assert client.get(f"/api/inquiries/{inquiry.id}").json()["photo_request"] == "나중에"
    client.cookies.clear()

    t = token(client)
    r = client.post("/api/inquiries/follow-up", json={"inquiry_number": inquiry.inquiry_number, "customer_email": "customer01@example.com",
                                                     "password": PW, "content": "사진 보내 드려요", "attachment_tokens": [t]})
    assert r.status_code == 201
    db.expire_all()
    assert db.get(Inquiry, inquiry.id).photo_request is None                     # 사진이 오면 풀림


def test_customer_marked_damage_and_label_check(client, db, ai):
    r = post(client, "상품 상태가 이상해요", damage_report=True)                  # 단어가 없어도 고객이 '파손 문의예요'를 고름
    assert r.status_code == 422 and r.json()["code"] == "PHOTO_REQUIRED"
    r = post(client, "상품 상태가 이상해요", photo_labels={"없는토큰": "송장"})    # 올리지 않은 사진에 이름표
    assert r.status_code == 422 and r.json()["code"] == "INVALID_FILE"


def test_customer_can_untick_damage_and_add_order_later(client, db, ai):
    """체크를 풀면(파손 문의 아님) 사진 없이 등록 · 추가 문의로 빠뜨린 주문번호를 붙임"""
    r = post(client, "상품이 파손되면 교환되나요?", damage_report=False)                 # 일반 질문: 고객이 자동 체크를 풂
    assert r.status_code == 201
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == r.json()["inquiry_number"]))
    assert inquiry.photo_request is None and inquiry.order_number is None

    body = {"inquiry_number": inquiry.inquiry_number, "customer_email": "customer01@example.com", "password": PW,
            "content": "주문번호 보내 드려요"}
    assert client.post("/api/inquiries/follow-up", json={**body, "order_number": "2026111-0001"}).status_code == 422
    assert client.post("/api/inquiries/follow-up", json={**body, "order_number": "202611100001"}).status_code == 201
    db.expire_all()
    inquiry = db.get(Inquiry, inquiry.id)
    assert inquiry.order_number == "20261110-0001"
    assert inquiry.messages[-1].content.endswith("(주문번호 추가: 20261110-0001)")
    found = client.post("/api/inquiries/lookup", json={"customer_email": "customer01@example.com", "password": PW}).json()
    assert {i["inquiry_number"]: i["order_number"] for i in found["items"]}[inquiry.inquiry_number] == "20261110-0001"

    # 이미 주문번호가 있으면 바꾸지 않음
    client.post("/api/inquiries/follow-up", json={**body, "content": "다른 번호요", "order_number": "20261110-0002"})
    db.expire_all()
    assert db.get(Inquiry, inquiry.id).order_number == "20261110-0001"


def test_follow_up_fixes_wrong_order_number(client, db, ai):
    """처음에 없는 주문번호를 적었으면 고객 조회에 order_needs_fix, 추가 문의로 맞는 번호로 바뀜"""
    r = post(client, "배송이 언제 오나요?", order_number="20261120-0222")           # 없는 주문
    number = r.json()["inquiry_number"]
    found = client.post("/api/inquiries/lookup", json={"customer_email": "customer01@example.com", "password": PW}).json()
    assert {i["inquiry_number"]: i["order_needs_fix"] for i in found["items"]}[number] is True

    body = {"inquiry_number": number, "customer_email": "customer01@example.com", "password": PW, "content": "번호를 잘못 적었어요"}
    assert client.post("/api/inquiries/follow-up", json={**body, "order_number": "20261110-0001"}).status_code == 201
    db.expire_all()
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == number))
    assert inquiry.order_number == "20261110-0001"
    assert inquiry.messages[-1].content.endswith("(주문번호 변경: 20261120-0222 → 20261110-0001)")


def test_one_photo_and_later_keeps_photo_request(client, db, ai):
    """송장 사진만 올리고 '지금은 사진이 없어요' → 나머지 사진을 나중에 받음 (상담원·고객 안내가 사라지지 않게)"""
    one = token(client)
    r = post(client, DAMAGE, attachment_tokens=[one], photo_labels={one: "송장"}, photos_later=True)
    assert r.status_code == 201
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == r.json()["inquiry_number"]))
    assert inquiry.photo_request == "나중에"
