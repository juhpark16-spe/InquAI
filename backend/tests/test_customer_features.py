"""실제 쇼핑몰 고객센터 기능 7가지: 개인정보 동의, 사진 첨부, 답변 평가, 추가 문의, 상담원 공유 메모, 답변 기한, 답변 알림."""

from datetime import timedelta

from sqlalchemy import select

from backend.database.models import Attachment, Inquiry, Notification, utcnow
from backend.services import sla
from backend.tests.conftest import TEST_PASSWORD
from backend.tests.test_inquiries import PW, ai, post, route_reply  # noqa: F401  (ai 는 fixture)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
EMAIL = "customer01@example.com"


def upload(client, data=PNG, name="파손.png"):
    return client.post("/api/inquiries/uploads", files={"file": (name, data, "image/png")})


def auto_answer(ai):
    ai["llm"].replies = {"route": route_reply("자동 답변", "FAQ 검색", ["F05"]),
                         "answer": {"answer": "보통 1~3일 안에 도착합니다.", "used_faq_ids": ["F05"], "grounded": True}}


def lookup(client, password=PW):
    return client.post("/api/inquiries/lookup", json={"customer_email": EMAIL, "password": password})


def admin_login(client, username="admin"):
    client.post("/api/auth/login", json={"username": username, "password": TEST_PASSWORD})
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


# ---- 1. 개인정보 동의 ----
def test_privacy_consent_required(client, db, ai):
    r = post(client, privacy_agreed=False)
    assert r.status_code == 422 and "개인정보" in str(r.json())
    body = {"customer_name": "a", "customer_email": EMAIL, "title": "t", "content": "동의 항목 없이 보냄", "password": PW}
    assert client.post("/api/inquiries", json=body).status_code == 422  # 항목을 아예 빼도 거부
    ai["analyzer"].next = {"confidence": 0.5}
    number = post(client).json()["inquiry_number"]
    assert db.scalar(select(Inquiry).where(Inquiry.inquiry_number == number)).privacy_agreed_at is not None


# ---- 2. 사진 첨부 ----
def test_upload_and_attach(client, db, ai):
    token = upload(client).json()["token"]
    ai["analyzer"].next = {"confidence": 0.5}
    # 파손 문의는 송장·파손 부위 두 장이 필요 → 한 장만 있으면 '지금은 사진이 없어요'(나머지는 나중에)로 (test_photo_evidence)
    number = post(client, content="상자가 찢어져서 왔어요", attachment_tokens=[token], photos_later=True).json()["inquiry_number"]
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == number))
    att = db.scalar(select(Attachment).where(Attachment.inquiry_id == inquiry.id))
    assert att.filename == "파손.png" and att.content_type == "image/png"

    h = admin_login(client)
    detail = client.get(f"/api/inquiries/{inquiry.id}").json()
    assert detail["attachments"][0]["filename"] == "파손.png" and "token" not in detail["attachments"][0]
    img = client.get(f"/api/inquiries/{inquiry.id}/attachments/{att.id}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content == PNG
    assert lookup(client).json()["items"][0]["attachment_count"] == 1
    del h


def test_upload_rejects_bad_files(client, ai):
    assert upload(client, b"<script>alert(1)</script>", "x.png").json()["code"] == "INVALID_FILE"  # 이름만 png
    assert upload(client, b"").status_code == 400
    assert upload(client, b"\xff\xd8\xff" + b"0" * (5 * 1024 * 1024)).json()["code"] == "FILE_TOO_LARGE"


def test_token_cannot_be_reused_or_guessed(client, ai):
    token = upload(client).json()["token"]
    ai["analyzer"].next = {"confidence": 0.5}
    assert post(client, attachment_tokens=[token]).status_code == 201
    assert post(client, attachment_tokens=[token]).json()["code"] == "INVALID_FILE"   # 이미 다른 문의에 연결됨
    assert post(client, attachment_tokens=["made-up"]).json()["code"] == "INVALID_FILE"
    assert post(client, attachment_tokens=["a", "b", "c", "d"]).status_code == 422     # 최대 3장


def test_old_upload_expires(client, db, ai):
    token = upload(client).json()["token"]
    att = db.scalar(select(Attachment).where(Attachment.token == token))
    att.created_at = utcnow() - timedelta(hours=2)
    db.commit()
    ai["analyzer"].next = {"confidence": 0.5}
    assert post(client, attachment_tokens=[token]).status_code == 400


def test_agent_cannot_see_other_attachments(client, db, ai):
    token = upload(client).json()["token"]
    ai["analyzer"].next = {"confidence": 0.5, "category": "결제"}
    db_id = db.scalar(select(Inquiry.id).where(Inquiry.inquiry_number == post(client, attachment_tokens=[token])
                                                .json()["inquiry_number"]))
    att_id = db.scalar(select(Attachment.id))
    from backend.core.security import hash_password
    from backend.database.models import AdminUser
    from backend.tests.conftest import TEST_PASSWORD
    other = AdminUser(username="agent2", role="agent", display_name="상담원2", password_hash=hash_password(TEST_PASSWORD))
    db.add(other)
    i = db.get(Inquiry, db_id)
    i.assigned_to = None
    db.commit()
    admin_login(client, "agent1")
    # 미배정 문의: 상세를 미리 볼 수 있으니 사진도 보임 (맡을지 판단)
    assert client.get(f"/api/inquiries/{db_id}/attachments/{att_id}").status_code == 200
    i.assigned_to = other.id                                       # 다른 상담원이 맡은 문의의 사진은 안 보임
    db.commit()
    assert client.get(f"/api/inquiries/{db_id}/attachments/{att_id}").status_code == 403


# ---- 3. 답변 평가 ----
def test_rate_answer(client, db, ai):
    auto_answer(ai)
    number = post(client).json()["inquiry_number"]
    answer = lookup(client).json()["items"][0]["answers"][0]
    assert answer["rating"] is None
    url = f"/api/inquiries/answers/{answer['id']}/rating?inquiry_number={number}"
    r = client.post(url, json={"customer_email": EMAIL, "password": PW, "helpful": False})
    assert r.json()["rating"] == -1
    client.post(url, json={"customer_email": EMAIL, "password": PW, "helpful": True})  # 다시 바꿀 수 있음
    assert lookup(client).json()["items"][0]["answers"][0]["rating"] == 1
    assert client.post(url, json={"customer_email": EMAIL, "password": "wrong-pw", "helpful": True}).status_code == 404

    admin_login(client)
    ratings = client.get("/api/stats/summary").json()["ratings"]
    assert ratings["ai"] == {"up": 1, "down": 0, "satisfaction": 1.0}


# ---- 4. 추가 문의 ----
def test_follow_up_reopens_and_assigns(client, db, ai):
    auto_answer(ai)
    number = post(client).json()["inquiry_number"]
    token = upload(client).json()["token"]
    r = client.post("/api/inquiries/follow-up", json={"customer_email": EMAIL, "password": PW, "inquiry_number": number,
                                                      "content": "그래도 아직 안 왔어요", "attachment_tokens": [token]})
    assert r.status_code == 201 and r.json()["status"] == "담당자 처리"

    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == number))
    db.refresh(inquiry)
    assert inquiry.status == "담당자 처리" and inquiry.assigned_to == 2  # 다시 열리고 상담원에게 배정
    item = lookup(client).json()["items"][0]
    assert [m["text"] for m in item["messages"]] == ["그래도 아직 안 왔어요"] and item["attachment_count"] == 1

    admin_login(client)
    d = client.get(f"/api/inquiries/{inquiry.id}").json()
    assert d["messages"][0]["text"] == "그래도 아직 안 왔어요" and d["attachments"][0]["message_id"] == d["messages"][0]["id"]
    assert any(e["kind"] == "followup" for e in d["history"])


def test_follow_up_with_photo_only(client, db, ai):
    """사진만 보내도 됨 (파손 사진을 나중에 보낼 때): 글이 없으면 '(사진 보냄)'으로 남김. 글도 사진도 없으면 422"""
    auto_answer(ai)
    number = post(client).json()["inquiry_number"]
    body = {"customer_email": EMAIL, "password": PW, "inquiry_number": number}
    assert client.post("/api/inquiries/follow-up", json={**body, "content": " "}).status_code == 422
    token = upload(client).json()["token"]
    assert client.post("/api/inquiries/follow-up", json={**body, "content": "", "attachment_tokens": [token]}).status_code == 201
    assert [m["text"] for m in lookup(client).json()["items"][0]["messages"]] == ["(사진 보냄)"]


def test_follow_up_requires_owner(client, ai):
    ai["analyzer"].next = {"confidence": 0.5}
    number = post(client).json()["inquiry_number"]
    r = client.post("/api/inquiries/follow-up", json={"customer_email": EMAIL, "password": "someone-else",
                                                      "inquiry_number": number, "content": "남의 문의"})
    assert r.status_code == 404


# ---- 5. 상담원 공유 메모 ----
def test_internal_notes(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.5}
    number = post(client).json()["inquiry_number"]
    inquiry_id = db.scalar(select(Inquiry.id).where(Inquiry.inquiry_number == number))
    h = admin_login(client)
    r = client.post(f"/api/inquiries/{inquiry_id}/notes", headers=h, json={"text": "택배사 확인 중, 내일 재연락"})
    assert r.status_code == 201 and r.json()["author"] == "관리자"
    assert client.get(f"/api/inquiries/{inquiry_id}").json()["notes"][0]["text"] == "택배사 확인 중, 내일 재연락"
    client.cookies.clear()
    assert "택배사 확인 중" not in lookup(client).text  # 고객에게는 안 보임
    assert client.post(f"/api/inquiries/{inquiry_id}/notes", json={"text": "x"}).status_code == 401


# ---- 6. 답변 기한 ----
def test_due_and_overdue(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.5, "urgency": "높음"}
    number = post(client).json()["inquiry_number"]
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == number))
    admin_login(client)
    item = client.get("/api/inquiries").json()["items"][0]
    assert item["overdue"] is False and item["due_at"].endswith("Z")
    inquiry.created_at = sla.sub_weekday_time(utcnow(), timedelta(hours=5))  # 긴급은 4시간 기한 (주말 제외, 평일 기준 5시간 전)
    db.commit()
    assert client.get("/api/inquiries").json()["items"][0]["overdue"] is True
    assert client.get("/api/stats/summary").json()["now"]["overdue_open"] == 1
    assert "영업일" in lookup(client).json()["notice"]


# ---- 7. 답변 알림 (시연용 기록) ----
def test_notifications(client, db, ai):
    auto_answer(ai)
    number = post(client).json()["inquiry_number"]
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == number))
    n = db.scalar(select(Notification).where(Notification.inquiry_id == inquiry.id))
    assert n.recipient == EMAIL and n.status == "기록"
    assert "1~3일" not in n.body and number in n.body  # 메일에는 답변 내용 대신 조회 안내만

    ai["analyzer"].next = {"confidence": 0.5}
    number2 = post(client).json()["inquiry_number"]
    inquiry2_id = db.scalar(select(Inquiry.id).where(Inquiry.inquiry_number == number2))
    h = admin_login(client)
    client.post(f"/api/inquiries/{inquiry2_id}/responses", headers=h, json={"text": "확인했습니다.", "send": True})
    assert len(client.get(f"/api/inquiries/{inquiry2_id}").json()["notifications"]) == 1


def test_overdue_filter(client, db, ai):
    ai["analyzer"].next = {"confidence": 0.5, "urgency": "높음"}
    old = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == post(client).json()["inquiry_number"]))
    ai["analyzer"].next = {"confidence": 0.5, "urgency": "보통"}
    post(client)
    old.created_at = sla.sub_weekday_time(utcnow(), timedelta(hours=5))
    db.commit()
    admin_login(client)
    assert [i["inquiry_number"] for i in client.get("/api/inquiries", params={"overdue": "true"}).json()["items"]] \
        == [old.inquiry_number]

def test_customer_sees_own_photos_with_signed_link(client, db, ai):
    token = upload(client).json()["token"]
    ai["analyzer"].next = {"confidence": 0.5}
    post(client, attachment_tokens=[token])
    photo = lookup(client).json()["items"][0]["attachments"][0]
    assert photo["filename"] == "파손.png" and photo["message_id"] is None
    r = client.get(photo["url"])  # 로그인 쿠키 없이 서명 주소로
    assert r.status_code == 200 and r.content == PNG

    att_id = photo["url"].split("/attachments/")[1].split("?")[0]
    assert client.get(photo["url"].replace("sig=", "sig=0")).status_code == 404            # 서명 위조
    assert client.get(f"/api/inquiries/attachments/{att_id}?exp=9999999999&sig=abc").status_code == 404
    import time as _t
    from backend.services import uploads as up
    old_exp = int(_t.time()) - 10
    assert client.get(f"/api/inquiries/attachments/{att_id}?exp={old_exp}&sig={up._sig(int(att_id), old_exp)}").status_code == 404  # 만료

def test_reopened_inquiry_restarts_due_time(client, db, ai):
    """3일 전에 답한 문의에 추가 문의가 오면 다시 연 시각부터 기한을 셈 (바로 '기한 초과'가 되지 않게)"""
    auto_answer(ai)
    number = post(client).json()["inquiry_number"]
    inquiry = db.scalar(select(Inquiry).where(Inquiry.inquiry_number == number))
    inquiry.created_at = sla.sub_weekday_time(utcnow(), timedelta(days=3))
    db.commit()
    r = client.post("/api/inquiries/follow-up", json={"inquiry_number": number, "customer_email": EMAIL, "password": PW,
                                                     "content": "아직 해결이 안 됐어요"})
    assert r.status_code == 201
    admin_login(client)
    item = next(i for i in client.get("/api/inquiries").json()["items"] if i["inquiry_number"] == number)
    assert item["status"] == "담당자 처리" and item["overdue"] is False
    assert client.get("/api/inquiries", params={"overdue": "true"}).json()["total"] == 0


def test_purge_unclaimed_uploads(client, db):
    """문의에 연결되지 않고 1시간이 지난 사진은 서버가 켜질 때 파일·기록을 지움 (방금 올린 사진은 남김)"""
    from backend.services import uploads

    old = upload(client).json()["token"]
    fresh = upload(client).json()["token"]
    a_old = db.scalar(select(Attachment).where(Attachment.token == old))
    a_old.created_at = utcnow() - timedelta(hours=2)
    db.commit()
    path = uploads.file_path(a_old)
    assert path.exists()
    assert uploads.purge_unclaimed(db) == 1
    db.commit()
    assert not path.exists()
    assert {a.token for a in db.scalars(select(Attachment))} == {fresh}
