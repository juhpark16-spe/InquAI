"""문의 등록·조회 API 테스트. 분류 모델과 LLM은 가짜로 바꿔 흐름(규칙·도구·저장·상태)만 확인합니다.

실제 모델·LLM 품질은 backend/training/evaluate.py, backend/agents/evaluate_agent.py 로 따로 검증합니다.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from backend.ai.rules import get_route, get_urgency
from backend.core import rate_limit
from backend.database.models import AgentLog, AnalysisResult, Customer, Inquiry, Order, Response, Ticket, utcnow
from backend.main import app
from backend.rag.faq_search import FaqSearch

FAQS = [
    {"id": "F05", "category": "배송", "question": "배송은 며칠 걸리나요?",
     "answer": "평일 오후 2시 이전 결제는 당일 출고되며 보통 1~3일 안에 도착합니다."},
    {"id": "F14", "category": "반품·환불", "question": "반품 배송비는 얼마인가요?",
     "answer": "단순 변심 반품은 왕복 배송비 6,000원을 고객님이 부담합니다."},
]


class FakeAnalyzer:
    def __init__(self):
        self.next = {}

    def analyze(self, text):
        a = {"category": "배송", "confidence": 0.95, "sentiment": "중립", "sentiment_confidence": 0.9}
        a.update(self.next)
        a["route"] = get_route(a["category"])
        a["urgency"] = a.get("urgency") or get_urgency(a["category"], a["sentiment"], text)
        return {**a, "scores": {}, "model_version": "test"}


class FakeLLM:
    label = "fake-llm (reasoning_effort=low)"

    def __init__(self):
        self.replies = {}   # name("route"/"answer") → dict 또는 Exception
        self.calls = []
        self.inputs = {}    # name → 마지막으로 받은 입력 (프롬프트에 무엇이 들어갔는지 확인용)

    def json(self, system, user, schema, name, timeout):
        self.calls.append(name)
        self.inputs[name] = user
        reply = self.replies[name]
        if isinstance(reply, Exception):
            raise reply
        return reply, {"input": 100, "output": 50}


@pytest.fixture()
def ai(client, db):
    customer = Customer(name="김민준", email="customer01@example.com", phone="010-0000-0000")
    db.add(customer)
    db.flush()
    db.add(Order(customer_id=customer.id, order_number="20261110-0001", product_name="맨투맨", amount=39000,
                 order_status="배송 중", shipping_status="대전 HUB 도착", tracking_number="123456789012",
                 ordered_at=utcnow() - timedelta(days=2)))
    db.commit()
    fake = {"analyzer": FakeAnalyzer(), "llm": FakeLLM()}
    app.state.analyzer, app.state.llm, app.state.faq_search = fake["analyzer"], fake["llm"], FaqSearch(FAQS)
    return fake


PW = "my-lookup-pw"


def post(client, content="배송은 보통 며칠 걸려요?", **extra):
    body = {"customer_name": "김민준", "customer_email": "Customer01@Example.com", "title": "문의",
            "content": content, "password": PW, "privacy_agreed": True, **extra}
    return client.post("/api/inquiries", json=body)


def lookup(client, email="customer01@example.com", password=PW):
    return client.post("/api/inquiries/lookup", json={"customer_email": email, "password": password})


def route_reply(decision, tool, faq_ids=(), reason="테스트"):
    return {"decision": decision, "tool": tool, "faq_ids": list(faq_ids), "reason": reason}


def saved(db, number):
    db.expire_all()
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == number))
    log = db.scalar(select(AgentLog).where(AgentLog.inquiry_id == inquiry.id))
    return inquiry, log


def test_auto_answer(client, db, ai):
    ai["llm"].replies = {"route": route_reply("자동 답변", "FAQ 검색", ["F05"]),
                         "answer": {"answer": "보통 1~3일 안에 도착합니다.", "used_faq_ids": ["F05"], "grounded": True}}
    r = post(client)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "자동 처리" and body["answer"] == "보통 1~3일 안에 도착합니다."
    assert body["inquiry_number"].startswith("INQ-") and body["inquiry_number"].endswith("-0001")
    assert set(body) == {"inquiry_number", "status", "answer", "message"}  # 분석 결과는 고객에게 안 보임

    inquiry, log = saved(db, body["inquiry_number"])
    assert inquiry.customer_email == "customer01@example.com"  # 소문자로 저장
    analysis = db.scalar(select(AnalysisResult).where(AnalysisResult.inquiry_id == inquiry.id))
    assert (analysis.decision, analysis.decided_by, analysis.route) == ("자동 답변", "LLM", "조회형")
    response = db.scalar(select(Response).where(Response.inquiry_id == inquiry.id))
    assert response.status == "발송" and response.approved_at is not None and response.used_faq_ids == ["F05"]
    assert log.selected_tool == "FAQ 검색" and log.tokens == {"input": 200, "output": 100, "calls": 2}
    assert log.retrieved_faqs[0][0] == "F05" and log.llm_model == FakeLLM.label


def test_not_grounded_becomes_draft(client, db, ai):
    ai["llm"].replies = {"route": route_reply("자동 답변", "FAQ 검색", ["F05"]),
                         "answer": {"answer": "확인 후 안내드리겠습니다.", "used_faq_ids": [], "grounded": False}}
    body = post(client).json()
    assert body["status"] == "검토 대기" and body["answer"] is None
    inquiry, log = saved(db, body["inquiry_number"])
    assert db.scalar(select(Response).where(Response.inquiry_id == inquiry.id)).status == "초안"
    assert log.decision == "답변 초안" and "근거 부족" in log.reason


def test_low_confidence_escalates_without_llm(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.6}
    body = post(client).json()
    assert body["status"] == "담당자 처리" and body["answer"] is None
    assert ai["llm"].calls == []
    inquiry, log = saved(db, body["inquiry_number"])
    assert (log.decided_by, log.selected_tool) == ("규칙", "상담원 이관")
    assert db.scalar(select(Ticket).where(Ticket.inquiry_id == inquiry.id)).ticket_type == "이관"


def test_llm_error_goes_to_review(client, db, ai):
    ai["llm"].replies = {"route": TimeoutError("timeout")}
    body = post(client).json()
    assert body["status"] == "검토 대기" and body["message"].startswith("문의가 접수")
    _, log = saved(db, body["inquiry_number"])
    assert log.error.startswith("TimeoutError") and log.decision == "답변 초안"


def test_shipping_lookup_with_own_order(client, db, ai):
    ai["llm"].replies = {"route": route_reply("답변 초안", "배송 조회")}
    body = post(client, content="제 주문 어디쯤 왔어요?", order_number="20261110-0001").json()
    assert body["status"] == "검토 대기"
    _, log = saved(db, body["inquiry_number"])
    assert log.tool_success is True and log.tool_output["shipping_status"] == "대전 HUB 도착"


def test_order_email_mismatch_escalates(client, db, ai):
    ai["llm"].replies = {"route": route_reply("답변 초안", "배송 조회")}
    r = client.post("/api/inquiries", json={"customer_name": "남", "customer_email": "other@example.com",
                                            "title": "문의", "content": "제 주문 어디쯤 왔어요?",
                                            "order_number": "20261110-0001", "password": PW,
                                            "privacy_agreed": True})
    body = r.json()
    assert body["status"] == "담당자 처리"
    _, log = saved(db, body["inquiry_number"])
    assert log.reason == "주문번호와 이메일이 일치하지 않음" and log.tool_output == {"ticket_id": 1}


def test_ticket_for_return(client, db, ai):
    ai["analyzer"].next = {"category": "반품·환불"}
    ai["llm"].replies = {"route": route_reply("답변 초안", "티켓 접수")}
    body = post(client, content="사이즈가 안 맞아서 반품하고 싶어요", order_number="20261110-0001").json()
    inquiry, log = saved(db, body["inquiry_number"])
    ticket = db.scalar(select(Ticket).where(Ticket.inquiry_id == inquiry.id))
    assert ticket.ticket_type == "환불" and ticket.order_id is not None and ticket.status == "접수"
    assert log.tool_output["ticket_id"] == ticket.id


def test_ticket_without_order_number(client, db, ai):
    ai["analyzer"].next = {"category": "교환"}
    ai["llm"].replies = {"route": route_reply("답변 초안", "티켓 접수")}
    body = post(client, content="색상을 다른 걸로 바꾸고 싶어요").json()
    inquiry, log = saved(db, body["inquiry_number"])
    assert log.tool_success is False and db.scalar(select(Ticket)) is None


def test_inquiry_numbers_increase(client, ai):
    ai["analyzer"].next = {"confidence": 0.5}
    numbers = [post(client).json()["inquiry_number"] for _ in range(3)]
    assert [n[-4:] for n in numbers] == ["0001", "0002", "0003"]


def test_password_is_hashed(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.5}
    inquiry, _ = saved(db, post(client).json()["inquiry_number"])
    assert inquiry.lookup_password_hash.startswith("$argon2") and PW not in inquiry.lookup_password_hash


def test_lookup(client, ai):
    ai["llm"].replies = {"route": route_reply("자동 답변", "FAQ 검색", ["F05"]),
                         "answer": {"answer": "보통 1~3일입니다.", "used_faq_ids": ["F05"], "grounded": True}}
    number = post(client).json()["inquiry_number"]

    ok = lookup(client, email="Customer01@EXAMPLE.com")  # 대소문자 구분 없음
    assert ok.status_code == 200
    item = ok.json()["items"][0]
    assert item["inquiry_number"] == number and item["answer"] == "보통 1~3일입니다." and item["answered_at"]

    wrong_email = lookup(client, email="x@example.com")
    wrong_password = lookup(client, password="wrong-password")
    assert wrong_email.status_code == wrong_password.status_code == 404
    assert wrong_email.json() == wrong_password.json()  # 무엇이 틀렸는지 알려주지 않음


def test_lookup_lists_only_same_password(client, ai):
    """같은 이메일이라도 비밀번호가 다른 문의는 보이지 않음 (남이 내 이메일로 문의해도 내 문의는 못 봄)"""
    ai["analyzer"].next = {"confidence": 0.5}
    first = post(client, content="첫 번째 문의입니다").json()["inquiry_number"]
    second = post(client, content="두 번째 문의입니다").json()["inquiry_number"]
    other = post(client, content="다른 사람이 같은 이메일로 쓴 문의", password="someone-else").json()["inquiry_number"]

    mine = [i["inquiry_number"] for i in lookup(client).json()["items"]]
    assert mine == [second, first]  # 최신순
    assert [i["inquiry_number"] for i in lookup(client, password="someone-else").json()["items"]] == [other]


def test_lookup_locks_after_failures(client, ai):
    ai["analyzer"].next = {"confidence": 0.5}
    post(client)
    codes = [lookup(client, password=f"wrong-{n}").status_code for n in range(5)]
    assert codes == [404] * 5
    r = lookup(client)  # 맞는 비밀번호여도 잠김
    assert r.status_code == 429 and "15분" in r.json()["detail"]


def test_draft_is_not_shown_in_lookup(client, ai):
    ai["llm"].replies = {"route": route_reply("자동 답변", "FAQ 검색", ["F05"]),
                         "answer": {"answer": "초안 내용", "used_faq_ids": [], "grounded": False}}
    post(client)
    item = lookup(client).json()["items"][0]
    assert item["answer"] is None and item["status"] == "검토 대기"


@pytest.mark.parametrize("field,value", [("content", "짧음"), ("customer_email", "not-an-email"), ("title", ""),
                                         ("password", "12345")])
def test_validation(client, ai, field, value):
    assert post(client, **{field: value}).status_code == 422


def test_rate_limit(client, ai):
    ai["analyzer"].next = {"confidence": 0.5}
    codes = [post(client).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]


def test_model_not_ready(client, ai):
    app.state.analyzer = None
    r = post(client)
    assert r.status_code == 503 and r.json()["code"] == "MODEL_NOT_READY"


def test_order_number_format(client, db, ai):
    """주문번호는 주문일 8자리-순번 4자리. 12자리 숫자·공백은 고쳐서 받고, 형식이 다르면 422 (안내 문장 그대로)"""
    r = post(client, order_number="20261120-022")
    assert r.status_code == 422 and "숫자 8자리-4자리" in r.json()["detail"][0]["msg"]
    assert post(client, order_number="A-2").status_code == 422
    for raw in ("202611100001", " 20261110-0001 ", "20261110 - 0001"):
        rate_limit.reset()                                                         # 문의 등록 1분 5건 제한
        number = post(client, order_number=raw).json()["inquiry_number"]
        assert db.scalar(select(Inquiry.order_number).where(Inquiry.inquiry_number == number)) == "20261110-0001", raw
    rate_limit.reset()
    number = post(client, order_number="  ").json()["inquiry_number"]                 # 빈칸 = 주문번호 없음
    assert db.scalar(select(Inquiry.order_number).where(Inquiry.inquiry_number == number)) is None
