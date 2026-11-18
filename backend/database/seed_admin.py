"""처음 관리자·상담원 계정 만들기. 이후 계정은 관리자가 계정 관리 화면(/admin/users)에서 만듭니다.
공개 회원가입은 없습니다 (관리자 화면에서 고객 개인정보가 보이기 때문).

비밀번호는 .env 의 SEED_ADMIN_PASSWORD, SEED_AGENT_PASSWORD 에서 읽습니다.
SEED_CUSTOMER_PASSWORD 가 있으면 시연 고객(customerNN@example.com)에게 쇼핑몰 로그인 비밀번호도 넣습니다 (연동 시연).
이미 있는 계정은 건너뜁니다. 비밀번호를 바꾸려면 --reset-password 를 붙입니다.

실행 (프로젝트 루트에서)
    python -m backend.database.seed_admin
    python -m backend.database.seed_admin --reset-password
"""

import argparse
import sys

from sqlalchemy import select

from backend.core.config import get_settings
from backend.core.security import hash_password
from backend.database.models import AdminUser, Customer, utcnow
from backend.database.session import SessionLocal, init_db

# (아이디, 역할, 화면 이름, 비밀번호 설정 이름, 담당 유형 — 비우면 전체 담당)
ACCOUNTS = [
    ("admin", "admin", "관리자", "seed_admin_password", []),
    ("agent1", "agent", "상담원 김하늘", "seed_agent_password", ["주문 취소", "반품·환불", "결제"]),
    ("agent2", "agent", "상담원 이준호", "seed_agent_password", ["배송", "교환", "상품"]),
]


def check_passwords() -> None:
    settings = get_settings()
    min_len = settings.password_min_length
    for _, _, _, key, _ in ACCOUNTS:
        if len(getattr(settings, key)) < min_len:
            raise SystemExit(f".env 의 {key.upper()} 를 {min_len}자 이상으로 넣어 주세요.")
    if min_len < 8:
        print(f"[주의] 비밀번호 최소 길이가 {min_len}자입니다. 시연용 로컬 환경에서만 쓰고, 배포할 때는 8자 이상으로 바꿔 주세요.")


def seed_accounts(db, reset_password: bool = False) -> None:
    """ACCOUNTS 계정을 만듭니다 (커밋은 부르는 쪽에서). seed_demo 에서도 씀"""
    settings = get_settings()
    for username, role, name, key, categories in ACCOUNTS:
        user = db.scalar(select(AdminUser).where(AdminUser.username == username))
        if user is None:
            db.add(AdminUser(username=username, role=role, display_name=name, categories=categories,
                             password_hash=hash_password(getattr(settings, key))))
            print(f"[생성] {username} ({role})")
        elif reset_password:
            user.password_hash = hash_password(getattr(settings, key))
            user.failed_login_count, user.locked_until = 0, None
            user.password_changed_at = utcnow()
            user.token_version = (user.token_version or 0) + 1
            print(f"[비밀번호 변경] {username}")
        else:
            print(f"[건너뜀] {username} 이미 있음")


def seed_customer_passwords(db, reset_password: bool = False) -> None:
    """시연 고객에게 쇼핑몰 로그인 비밀번호를 넣습니다 (회원가입 없음). SEED_CUSTOMER_PASSWORD 가 비면 건너뜀"""
    password = get_settings().seed_customer_password
    if not password:
        print("[고객 로그인] SEED_CUSTOMER_PASSWORD 가 없어 건너뜀 (비회원 문의만 사용)")
        return
    customers = db.scalars(select(Customer).where(True if reset_password else Customer.password_hash.is_(None))).all()
    hashed = hash_password(password)   # 시연 고객은 모두 같은 비밀번호 (한 번만 계산)
    for c in customers:
        c.password_hash = hashed
    print(f"[고객 로그인] 시연 고객 {len(customers)}명에게 비밀번호 설정 (customerNN@example.com)")


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="관리자·상담원 계정 만들기")
    p.add_argument("--reset-password", action="store_true", help="이미 있는 계정의 비밀번호도 .env 값으로 바꿈")
    args = p.parse_args()

    check_passwords()
    init_db()
    with SessionLocal() as db:
        seed_accounts(db, args.reset_password)
        seed_customer_passwords(db, args.reset_password)
        db.commit()


if __name__ == "__main__":
    main()
