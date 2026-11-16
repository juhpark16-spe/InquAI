"""고객용 FAQ API 테스트: 목록(활성만), 비슷한 FAQ 추천."""

import pytest

from backend.database.models import Faq
from backend.main import app
from backend.rag.faq_search import FaqSearch

FAQS = [
    ("F14", "배송", "주문하면 배송은 얼마나 걸리나요?", "평일 오후 2시 이전 주문은 당일 출고됩니다."),
    ("F17", "반품·환불", "반품 배송비는 얼마인가요?", "단순 변심 반품은 왕복 배송비 6,000원입니다."),
    ("F38", "쿠폰·적립금·회원", "아이디가 기억나지 않아요.", "아이디 찾기에서 본인 인증을 하시면 됩니다."),
]


@pytest.fixture()
def faqs(client, db):
    for code, cat, q, a in FAQS:
        db.add(Faq(code=code, category=cat, question=q, answer=a))
    db.add(Faq(code="F99", category="기타", question="비활성 FAQ", answer="보이면 안 됨", is_active=False))
    db.commit()
    app.state.faq_search = FaqSearch.from_db(db)


def test_list_public_faqs(client, faqs):
    r = client.get("/api/public/faqs")
    assert r.status_code == 200
    assert [f["code"] for f in r.json()] == ["F14", "F17", "F38"]  # 비활성 제외
    assert set(r.json()[0]) == {"code", "category", "question", "answer"}  # 내부 id·수정일 등은 내보내지 않음


def test_suggest(client, faqs):
    r = client.get("/api/public/faqs/suggest", params={"q": "반품하면 배송비 얼마 내야 돼요?"})
    assert r.status_code == 200 and r.json()[0]["code"] == "F17"


def test_suggest_unrelated_returns_nothing(client, faqs):
    assert client.get("/api/public/faqs/suggest", params={"q": "ㅋㅋㅋㅋ 안녕하세요"}).json() == []


def test_suggest_validation(client, faqs):
    assert client.get("/api/public/faqs/suggest", params={"q": "a"}).status_code == 422
    assert client.get("/api/public/faqs/suggest", params={"q": "배송", "k": 9}).status_code == 422


def test_suggest_rate_limit(client, faqs):
    codes = [client.get("/api/public/faqs/suggest", params={"q": "배송 기간"}).status_code for _ in range(31)]
    assert codes[-1] == 429 and codes[:30] == [200] * 30
