"""고객 답변 알림 메일: 기본은 기록만, 켜면 커밋 뒤에 따로 보내고 결과를 기록 (실제 메일 대신 가짜 SMTP)."""

import smtplib

import pytest

from backend.core.config import get_settings
from backend.database.models import Inquiry, Notification
from backend.services import notify
from backend.tests.conftest import TEST_PASSWORD

AGENT = 2
REAL = "kim.customer@mail-inquai.co.kr"   # 가짜 SMTP라 실제로는 나가지 않음


def login(client, username="agent1"):
    client.cookies.clear()
    client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")


def make(db, email=REAL, n=1):
    i = Inquiry(inquiry_number=f"INQ-M-{n}", customer_name="김고객", customer_email=email, title="사이즈 문의",
                content="M 사이즈 실측이 궁금해요", status="담당자 처리", assigned_to=AGENT)
    db.add(i)
    db.commit()
    return i.id


@pytest.fixture()
def mail(monkeypatch):
    """메일 켜기 + 가짜 SMTP + 바로 실행 (별도 스레드 대신)"""
    s = get_settings()
    monkeypatch.setattr(s, "mail_enabled", True)
    monkeypatch.setattr(s, "mail_redirect_to", "")
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(notify, "smtp_send", lambda to, subject, body: sent.append((to, subject, body)))
    monkeypatch.setattr(notify, "run_later", lambda job: job())
    return sent


def answer(client, inquiry_id, **extra):
    return client.post(f"/api/inquiries/{inquiry_id}/responses", json={"text": "실측표를 안내드립니다.", "send": True, **extra})


def test_default_only_records(client, db):
    inquiry_id = make(db)
    login(client)
    assert answer(client, inquiry_id).status_code == 201
    d = client.get(f"/api/inquiries/{inquiry_id}").json()
    assert d["notifications"][0]["status"] == "기록"
    assert any(e["kind"] == "mail" and "메일 발송 꺼짐" in e["text"] for e in d["history"])


def test_sends_after_commit_and_records_result(client, db, mail):
    inquiry_id = make(db)
    login(client)
    assert answer(client, inquiry_id).status_code == 201
    assert len(mail) == 1
    to, subject, body = mail[0]
    assert to == REAL and "답변이 등록되었습니다" in subject
    assert "INQ-M-1" in body and "/inquiry/lookup" in body and "실측표" not in body   # 본문에 답변 내용은 넣지 않음
    d = client.get(f"/api/inquiries/{inquiry_id}").json()
    n = d["notifications"][0]
    assert n["status"] == "발송" and n["sent_at"] and n["error"] is None
    assert any(e["text"] == f"고객 알림 메일 발송 → {REAL}" for e in d["history"])


def test_redirect_fake_address_and_failure(client, db, mail, monkeypatch):
    login(client)
    fake = make(db, "customer01@example.com", 1)
    assert answer(client, fake).status_code == 201                       # 예시 주소 → 보내지 않음
    assert mail == [] and client.get(f"/api/inquiries/{fake}").json()["notifications"][0]["status"] == "건너뜀"

    monkeypatch.setattr(get_settings(), "mail_redirect_to", "demo-inbox@mail-inquai.co.kr")   # 시연: 한 주소로
    redirected = make(db, "customer02@example.com", 2)
    assert answer(client, redirected).status_code == 201
    assert mail[0][0] == "demo-inbox@mail-inquai.co.kr" and "원래 받는 사람: customer02@example.com" in mail[0][1]

    def broken(*_):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
    monkeypatch.setattr(notify, "smtp_send", broken)
    failed = make(db, REAL, 3)
    assert answer(client, failed).status_code == 201                     # 메일이 실패해도 답변은 보내짐
    n = client.get(f"/api/inquiries/{failed}").json()["notifications"][0]
    assert n["status"] == "실패" and "SMTPAuthenticationError" in n["error"]


def test_no_mail_when_send_is_rolled_back(client, db, mail):
    inquiry_id = make(db)
    login(client)
    r = answer(client, inquiry_id, recheck={"note": "x", "due_at": "2020-01-01T00:00:00Z"})   # 지난 기한 → 422, 저장 안 됨
    assert r.status_code == 422 and mail == []
    assert db.query(Notification).count() == 0
