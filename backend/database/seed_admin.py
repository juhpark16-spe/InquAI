"""관리자·상담원 계정 만들기 (공개 회원가입이 없어 계정은 이 스크립트로만 만듭니다).

비밀번호는 .env 의 SEED_ADMIN_PASSWORD, SEED_AGENT_PASSWORD 에서 읽습니다.
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
from backend.database.models import AdminUser
from backend.database.session import SessionLocal, init_db

# (아이디, 역할, 화면 이름, 비밀번호 설정 이름)
ACCOUNTS = [
    ("admin", "admin", "관리자", "seed_admin_password"),
    ("agent1", "agent", "상담원 김하늘", "seed_agent_password"),
    ("agent2", "agent", "상담원 이준호", "seed_agent_password"),
]
MIN_PASSWORD_LENGTH = 8


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="관리자·상담원 계정 만들기")
    p.add_argument("--reset-password", action="store_true", help="이미 있는 계정의 비밀번호도 .env 값으로 바꿈")
    args = p.parse_args()

    settings = get_settings()
    for _, _, _, key in ACCOUNTS:
        if len(getattr(settings, key)) < MIN_PASSWORD_LENGTH:
            raise SystemExit(f".env 의 {key.upper()} 를 {MIN_PASSWORD_LENGTH}자 이상으로 넣어 주세요.")

    init_db()
    with SessionLocal() as db:
        for username, role, name, key in ACCOUNTS:
            user = db.scalar(select(AdminUser).where(AdminUser.username == username))
            if user is None:
                db.add(AdminUser(username=username, role=role, display_name=name,
                                 password_hash=hash_password(getattr(settings, key))))
                print(f"[생성] {username} ({role})")
            elif args.reset_password:
                user.password_hash = hash_password(getattr(settings, key))
                user.failed_login_count, user.locked_until = 0, None
                print(f"[비밀번호 변경] {username}")
            else:
                print(f"[건너뜀] {username} 이미 있음")
        db.commit()


if __name__ == "__main__":
    main()
