"""AI 답변 초안: 접수 때 자동 초안(답변 초안 판단), 상세 화면의 [AI 초안 만들기] (POST /api/inquiries/{id}/draft)"""

from sqlalchemy import select

from backend.database.models import AgentLog, Customer, Inquiry, Order, Response
from backend.main import app
from backend.tests.conftest import TEST_PASSWORD
from backend.tests.test_inquiries import ai, post, route_reply, saved  # noqa: F401  (fixture 재사용)

DRAFT = {"answer": "불편을 드려 죄송합니다. 주문하신 맨투맨은 대전 HUB에 도착했습니다 (F05). [확인 필요: 도착 예정일]",
         "used_faq_ids": ["F05", "F99"], "grounded": True, "check_points": ["도착 예정일", " "]}


class Recorder:
    """FakeLLM을 감싸 LLM에 넘긴 글을 기록"""

    def __init__(self, llm):
        self.llm, self.inputs, self.label = llm, {}, llm.label

    def json(self, system, user, schema, name, timeout):
        self.inputs[name] = user
        return self.llm.json(system, user, schema, name, timeout)


def login(client, username="admin"):
    client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def test_review_decision_gets_draft_at_registration(client, db, ai):
    ai["llm"].replies = {"route": route_reply("답변 초안", "배송 조회"), "draft": DRAFT}
    rec = Recorder(ai["llm"])
    app.state.llm = rec
    body = post(client, content="맨투맨 언제 와요?", order_number="20261110-0001").json()
    assert body["status"] == "검토 대기" and body["answer"] is None          # 초안은 고객에게 안 보임

    inquiry, log = saved(db, body["inquiry_number"])
    draft = db.scalar(select(Response).where(Response.inquiry_id == inquiry.id))
    assert draft.status == "초안" and draft.generated_by == "llm"
    assert draft.draft_text == DRAFT["answer"].replace(" (F05)", "")             # FAQ 번호는 고객 글에서 지움
    assert draft.used_faq_ids == ["F05"]                                     # 넘기지 않은 F99는 버림
    assert draft.check_points == ["도착 예정일"] and draft.grounded is False   # [확인 필요]가 있으면 근거 부족
    assert log.tokens["calls"] == 2 and log.error is None and log.response_text == draft.draft_text

    sent = rec.inputs["draft"]
    assert "대전 HUB 도착" in sent and "맨투맨" in sent                        # 본인 확인된 주문 정보
    assert "김민준" not in sent and "customer01" not in sent.lower()          # 이름·이메일은 넘기지 않음
    assert "[첨부 사진] 없음" in sent


def test_draft_failure_keeps_inquiry_for_review(client, db, ai):
    ai["llm"].replies = {"route": route_reply("답변 초안", "FAQ 검색"), "draft": TimeoutError("slow")}
    body = post(client).json()
    assert body["status"] == "검토 대기"
    inquiry, log = saved(db, body["inquiry_number"])
    assert db.scalar(select(Response).where(Response.inquiry_id == inquiry.id)) is None
    assert log.error.startswith("초안 작성 실패") and log.decision == "답변 초안"
    login(client)
    history = [e["text"] for e in client.get(f"/api/inquiries/{inquiry.id}").json()["history"]]
    assert any("초안 작성 실패" in t for t in history)


def test_draft_button_for_escalated_inquiry(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.6}                                # 규칙으로 담당자 연결 (LLM 안 씀)
    number = post(client, content="상품이 깨져서 왔어요").json()["inquiry_number"]
    inquiry, _ = saved(db, number)
    ai["llm"].replies = {"draft": {**DRAFT, "check_points": []}}
    h = login(client)

    r = client.post(f"/api/inquiries/{inquiry.id}/draft", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "초안" and d["generated_by"] == "llm" and d["final_text"] is None
    detail = client.get(f"/api/inquiries/{inquiry.id}").json()
    assert detail["responses"][-1]["id"] == d["id"]
    assert detail["history"][-1]["text"] == "AI 초안 만들기" and detail["history"][-1]["actor"] == "관리자"

    # 다시 만들면 같은 초안 자리에 씀 (초안이 둘 생기지 않음)
    r2 = client.post(f"/api/inquiries/{inquiry.id}/draft", headers=h)
    assert r2.json()["id"] == d["id"]
    assert len(db.scalars(select(Response).where(Response.inquiry_id == inquiry.id)).all()) == 1


def test_edited_draft_needs_replace(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.6}
    inquiry, _ = saved(db, post(client).json()["inquiry_number"])
    h = login(client)
    mine = client.post(f"/api/inquiries/{inquiry.id}/responses", headers=h, json={"text": "제가 쓰던 답변"}).json()
    ai["llm"].replies = {"draft": DRAFT}

    r = client.post(f"/api/inquiries/{inquiry.id}/draft", headers=h)
    assert r.status_code == 409 and r.json()["code"] == "DRAFT_EDITED"
    db.expire_all()
    assert db.get(Response, mine["id"]).final_text == "제가 쓰던 답변"       # 그대로

    r = client.post(f"/api/inquiries/{inquiry.id}/draft", headers=h, json={"replace": True})
    assert r.status_code == 200 and r.json()["id"] == mine["id"] and r.json()["generated_by"] == "llm"
    history = [e["text"] for e in client.get(f"/api/inquiries/{inquiry.id}").json()["history"]]
    assert history[-1] == "AI 초안 다시 만들기"


def test_draft_errors(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.6}
    inquiry, _ = saved(db, post(client).json()["inquiry_number"])
    h = login(client)
    ai["llm"].replies = {"draft": RuntimeError("api down")}
    r = client.post(f"/api/inquiries/{inquiry.id}/draft", headers=h)
    assert r.status_code == 502 and r.json()["code"] == "DRAFT_FAILED"
    assert db.scalar(select(Response).where(Response.inquiry_id == inquiry.id)) is None

    app.state.llm = None
    r = client.post(f"/api/inquiries/{inquiry.id}/draft", headers=h)
    assert r.status_code == 503 and r.json()["code"] == "LLM_UNAVAILABLE"


def test_agent_cannot_draft_unassigned_inquiry(client, db, ai):
    other = Inquiry(inquiry_number="INQ-D-9", customer_name="남", customer_email="x@example.com", title="t",
                    content="다른 문의", status="담당자 처리", assigned_to=None)
    db.add(other)
    db.commit()
    ai["llm"].replies = {"draft": DRAFT}
    h = login(client, "agent1")
    assert client.post(f"/api/inquiries/{other.id}/draft", headers=h).status_code in (403, 404)
    assert ai["llm"].calls == []


def test_other_persons_order_is_not_shared(client, db, ai):
    stranger = Customer(name="남", email="other@example.com", phone="010-1111-1111")
    db.add(stranger)
    db.flush()
    db.add(Order(customer_id=stranger.id, order_number="20261110-0099", product_name="비밀 상품", amount=99000,
                 order_status="배송 중", shipping_status="이동 중", ordered_at=db.scalar(select(Order.ordered_at))))
    db.commit()
    ai["analyzer"].next = {"confidence": 0.6}
    inquiry, _ = saved(db, post(client, order_number="20261110-0099").json()["inquiry_number"])
    ai["llm"].replies = {"draft": DRAFT}
    rec = Recorder(ai["llm"])
    app.state.llm = rec
    client.post(f"/api/inquiries/{inquiry.id}/draft", headers=login(client))
    assert "본인 확인 필요" in rec.inputs["draft"] and "비밀 상품" not in rec.inputs["draft"]
    assert db.scalar(select(AgentLog).where(AgentLog.inquiry_id == inquiry.id)).selected_tool == "상담원 이관"
