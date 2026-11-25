"""환불 계좌 (무통장입금 주문 취소·반품): 문의 글과 따로 받고, 고객·상담원 화면에는 가려서, [번호 보기]는 작업 기록,
AI 초안 입력에는 받았는지만 (번호는 넘기지 않음)."""

from sqlalchemy import select

from backend.agents.drafting import build_input
from backend.database.models import AdminAuditLog, AnalysisResult, Customer, Order, Ticket, utcnow
from backend.tests.test_customer_features import PW, admin_login, lookup
from backend.tests.test_inquiries import ai, post, saved  # noqa: F401  (fixture 재사용)

ACCOUNT = {"bank": "국민은행", "holder": "김민준", "number": "352-0987-6543-21"}


def bank_transfer_inquiry(client, db):
    """무통장입금 주문의 취소 문의 (환불 계좌가 필요한 경우)"""
    c = db.scalar(select(Customer).where(Customer.email == "customer01@example.com"))
    db.add(Order(customer_id=c.id, order_number="20261125-0777", product_name="니트", amount=45000, order_status="결제 완료",
                 payment_method="무통장입금", ordered_at=utcnow()))
    db.commit()
    number = post(client, content="주문번호 20261125-0777 니트 취소해 주세요", order_number="20261125-0777").json()["inquiry_number"]
    inquiry, _ = saved(db, number)
    if inquiry.analysis is None:
        db.add(AnalysisResult(inquiry_id=inquiry.id, category="주문 취소", confidence=0.9, sentiment="중립", sentiment_confidence=0.9,
                              urgency="보통", route="접수형", decision="답변 초안", decided_by="LLM", model_version="t", scores={}))
    db.add(Ticket(inquiry_id=inquiry.id, ticket_type="취소", reason="취소"))
    inquiry.assigned_to = 2
    db.commit()
    return inquiry


def test_follow_up_with_refund_account_only(client, db, ai):
    inquiry = bank_transfer_inquiry(client, db)
    item = lookup(client).json()["items"][0]
    assert item["refund_account_needed"] is True and item["refund_account"] is None      # 고객 화면에 칸을 펼침

    body = {"customer_email": "customer01@example.com", "password": PW, "inquiry_number": inquiry.inquiry_number,
            "content": "", "refund_account": ACCOUNT}
    assert client.post("/api/inquiries/follow-up", json=body).status_code == 201
    db.expire_all()
    assert inquiry.refund_account == "3520987654321" and inquiry.refund_bank == "국민은행"
    item = lookup(client).json()["items"][0]
    assert item["refund_account"]["number"] == "****4321" and item["refund_account"]["holder"] == "김*준"
    assert item["refund_account_needed"] is False
    assert "3520987654321" not in str(item) and "(환불 계좌 보냄)" in item["messages"][0]["text"]   # 대화에는 번호 없이

    # AI 초안 입력: 받았다는 사실만, 번호·예금주는 넣지 않음
    text = build_input(db, inquiry, [], None)
    assert "환불 계좌 받음" in text and "3520987654321" not in text and "4321" not in text


def test_bad_refund_account_is_rejected(client, db, ai):
    inquiry = bank_transfer_inquiry(client, db)
    base = {"customer_email": "customer01@example.com", "password": PW, "inquiry_number": inquiry.inquiry_number, "content": "계좌 보내요"}
    for bad in ({**ACCOUNT, "bank": "없는은행"}, {**ACCOUNT, "number": "1234"}, {**ACCOUNT, "number": "1234-abcd-5678"}):
        assert client.post("/api/inquiries/follow-up", json={**base, "refund_account": bad}).status_code == 422, bad


def test_staff_sees_masked_and_full_number_is_logged(client, db, ai):
    inquiry = bank_transfer_inquiry(client, db)
    post_body = {"customer_email": "customer01@example.com", "password": PW, "inquiry_number": inquiry.inquiry_number,
                 "content": "환불 계좌 보내 드려요", "refund_account": ACCOUNT}
    assert client.post("/api/inquiries/follow-up", json=post_body).status_code == 201
    client.cookies.clear()
    admin_login(client, "agent1")
    d = client.get(f"/api/inquiries/{inquiry.id}").json()
    assert d["refund_account"]["number"] == "****4321" and "3520987654321" not in str(d)   # 상세 화면은 가려서
    full = client.get(f"/api/inquiries/{inquiry.id}/refund-account").json()
    assert full["number"] == "3520987654321" and full["holder"] == "김민준"
    log = db.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "refund_account_view"))
    assert log.target_id == inquiry.id and log.admin_id == 2                           # 누가 봤는지 남음


def test_new_inquiry_can_carry_refund_account(client, db, ai):
    r = post(client, content="무통장으로 산 주문 취소하려고요", refund_account=ACCOUNT)
    assert r.status_code == 201
    inquiry, _ = saved(db, r.json()["inquiry_number"])
    assert inquiry.refund_account == "3520987654321" and "3520987654321" not in inquiry.content
