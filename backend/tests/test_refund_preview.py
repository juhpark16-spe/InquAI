"""문의하기의 환불 미리 보기 (backend/services/refund_preview.py): 회원이 고른 주문을 취소·반품하면 돌려받을 금액."""

from sqlalchemy import select

from backend.core.security import hash_password
from backend.database.models import Customer
from backend.services.policy import partial_refund
from backend.tests.test_order_actions import EMAIL, ids  # noqa: F401  (fixture 재사용)

PW = "shop-password-1234"


def shop_login(client, db):
    c = db.scalar(select(Customer).where(Customer.email == EMAIL))
    c.password_hash = hash_password(PW)
    db.commit()
    client.cookies.clear()
    assert client.post("/api/shop/login", json={"email": EMAIL, "password": PW}).status_code == 200


def test_preview_cancel_return_and_deadlines(client, db, ids):
    shop_login(client, db)
    ready = client.get("/api/shop/orders/R-1/refund-preview").json()          # 상품 준비 중, 2개 98,000원 (신용카드)
    assert ready["kind"] == "cancel" and ready["amount"] == 98000
    assert ready["partial"] == [{"count": 1, "refund": 49000, "fee": 0, "left": 49000}]
    assert "신용카드 3~5영업일" in ready["refund_timing"]
    done = client.get("/api/shop/orders/D-1/refund-preview").json()           # 배송 완료 3일, 79,000원
    assert done["kind"] == "return" and done["change_refund"] == 73000 and done["defect_refund"] == 79000
    old = client.get("/api/shop/orders/D-2/refund-preview").json()            # 배송 완료 12일 → 단순 변심 7일 지남
    assert old["change_refund"] is None and old["defect_refund"] == 79000
    assert client.get("/api/shop/orders/X-1/refund-preview").status_code == 404   # 다른 고객의 주문


def test_partial_refund_breaks_free_shipping():
    # 3만원 이상 무료배송 주문이 일부 취소로 3만원 미만이 되면 처음 배송비 3,000원을 빼고 환불 (바로 처리와 같은 계산)
    assert partial_refund(40000, 2, 1) == (17000, 3000, 20000)
    assert partial_refund(98000, 2, 1) == (49000, 0, 49000)
