"""FAQ 자동 추천 테스트 (TF-IDF 검색 + 가짜 LLM): 후보 고르기, 묶기, 초안 근거, FAQ를 추가하면 추천에서 빠짐, 권한."""

from datetime import timedelta

import pytest

from backend.database.models import AgentLog, AnalysisResult, Faq, Inquiry, Response, utcnow
from backend.main import app
from backend.rag.faq_search import FaqSearch
from backend.tests.conftest import TEST_PASSWORD

BULK = ["회사 행사용으로 텀블러 200개 단체 주문 견적 받을 수 있나요",
        "단체 주문 견적 문의드려요 회사 행사 기념품 텀블러 150개",
        "텀블러 단체 주문 견적서 받고 싶어요 회사 행사용 300개"]


class FakeLLM:
    label = "fake"

    def __init__(self):
        self.inputs = []

    def json(self, system, user, schema, name, timeout):
        self.inputs.append(user)
        return {"question": "단체 주문 견적은 어떻게 받나요?",
                "answer": "50개 이상은 단체 주문 견적을 드립니다. [확인 필요: 할인율]", "category": "상품",  # 무시됨
                "check_points": ["할인율", " "]}, {}


def add(db, n, text, *, decision="담당자 연결", urgency="보통", days_ago=1, staff_answer=None):
    created = utcnow() - timedelta(days=days_ago)
    i = Inquiry(inquiry_number=f"INQ-S-{n:04d}", customer_name="고객", customer_email=f"c{n}@example.com",
                title=text[:20], content=text, status="완료", created_at=created)
    db.add(i)
    db.flush()
    db.add(AnalysisResult(inquiry_id=i.id, category="기타", confidence=0.9, sentiment="중립", sentiment_confidence=0.9,
                          urgency=urgency, route="이관형", decision=decision, decided_by="규칙", model_version="t", scores={}))
    db.add(AgentLog(inquiry_id=i.id, category="기타", confidence=0.9, decision=decision, decided_by="규칙",
                    selected_tool="상담원 이관", created_at=created))
    if staff_answer:
        db.add(Response(inquiry_id=i.id, draft_text=staff_answer, final_text=staff_answer, status="발송", approved_by=1))
    return i


@pytest.fixture()
def data(client, db):
    db.add(Faq(code="F01", category="배송", question="배송은 며칠 걸리나요?", answer="보통 1~2일 걸립니다."))
    for n, text in enumerate(BULK, start=1):
        add(db, n, text, staff_answer="50개 이상은 단체 견적을 드립니다. 담당 부서에서 연락드릴게요." if n < 3 else None)
    add(db, 10, "앱 업데이트 후 화면이 하얗게 나와요")                                  # 비슷한 문의 없음 → 묶음 안 됨
    add(db, 11, "텀블러 단체 주문 견적 당장 보내세요 왜 답이 없어요", urgency="높음")      # 항의 → 제외
    add(db, 12, "텀블러 단체 주문 견적 가능한가요", decision="자동 답변")                   # 이미 자동 처리 → 제외
    add(db, 13, "텀블러 단체 주문 견적 부탁드립니다", days_ago=60)                         # 기간 밖
    db.commit()
    llm = FakeLLM()
    app.state.faq_search, app.state.llm = FaqSearch.from_db(db), llm
    return llm


def login_admin(client):
    assert client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD}).status_code == 200
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_groups_similar_unanswered_inquiries(client, data):
    headers = login_admin(client)
    r = client.post("/api/faqs/suggestions", json={"days": 30}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"] == 4 and body["engine"] == "tfidf"              # 묶음 3 + 앱 오류 1 (제외 조건 3건 빠짐)
    [item] = body["items"]
    assert item["count"] == 3 and item["with_staff_answer"] == 2 and item["drafted"] is True
    assert item["question"] == "단체 주문 견적은 어떻게 받나요?" and item["check_points"] == ["할인율"]
    assert item["category"] == "기타"                                            # 유형은 분류 결과 다수 (LLM 값 아님)
    assert {e["inquiry_number"] for e in item["examples"]} == {"INQ-S-0001", "INQ-S-0002", "INQ-S-0003"}
    # LLM에는 고객 글을 <고객 글>로 감싸고, 상담원이 보낸 답변을 근거로 넘김
    sent = data.inputs[0]
    assert "<고객 글>" in sent and "50개 이상은 단체 견적을 드립니다" in sent and "(아직 보낸 답변 없음)" in sent


def test_added_faq_removes_suggestion(client, db, data):
    headers = login_admin(client)
    r = client.post("/api/faqs", json={"category": "기타", "question": "회사 행사용 텀블러 단체 주문 견적 받을 수 있나요?",
                                      "answer": "50개 이상 단체 주문은 견적을 드립니다. 1:1 문의로 남겨 주세요."}, headers=headers)
    assert r.status_code == 201                                                  # 등록하면 검색 색인도 바로 바뀜
    after = client.post("/api/faqs/suggestions", json={"days": 30}, headers=headers).json()
    assert after["items"] == []


def test_without_llm_returns_groups_only(client, data):
    app.state.llm = None
    headers = login_admin(client)
    [item] = client.post("/api/faqs/suggestions", json={}, headers=headers).json()["items"]
    assert item["drafted"] is False and item["answer"] == "" and item["count"] == 3


def test_admin_only(client, data):
    assert client.post("/api/faqs/suggestions", json={}).status_code == 401
    client.post("/api/auth/login", json={"username": "agent1", "password": TEST_PASSWORD})
    assert client.post("/api/faqs/suggestions", json={},
                       headers={"X-CSRF-Token": client.cookies.get("csrf_token")}).status_code == 403
