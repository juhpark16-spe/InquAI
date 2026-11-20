"""화면 자동 테스트(Playwright, frontend/e2e)용 백엔드 서버.

개발 DB(data/inquai.db)·첨부 사진 폴더를 건드리지 않도록 임시 폴더에 새 DB를 만들고,
관리자·상담원 계정과 FAQ·모의 주문만 넣은 뒤 서버를 켭니다.
분류 모델·KURE·OpenAI·LangSmith는 쓰지 않습니다 (CI에는 모델과 API 키가 없음).
분류는 단어 규칙으로 하는 가짜 분석기(KeywordAnalyzer), LLM 판단·초안은 늘 같은 답을 주는 가짜 LLM(FakeLLM)이 대신합니다.
시험용 쇼핑몰 회원(customerNN@example.com)도 E2E_PASSWORD 로 로그인할 수 있습니다.

실행 (프로젝트 루트에서, 보통은 Playwright가 알아서 켬)
    python -m backend.tests.e2e_server --port 8001
"""

import argparse
import os
import re
import sys
import tempfile
from pathlib import Path

# backend 를 불러오기 전에 정해야 설정에 반영됩니다 (.env 보다 우선)
_tmp = Path(tempfile.mkdtemp(prefix="inquai_e2e_"))
E2E_PASSWORD = os.environ.get("E2E_PASSWORD", "e2e-test-password-1234")
os.environ.update({
    "DATABASE_URL": f"sqlite:///{(_tmp / 'e2e.db').as_posix()}",
    "JWT_SECRET_KEY": "e2e-only-secret-key-not-for-real-use-0123456789",
    "COOKIE_SECURE": "false",
    "LOAD_MODELS": "false",
    "OPENAI_API_KEY": "",
    "LANGSMITH_TRACING": "false",
    "PASSWORD_MIN_LENGTH": "8",
    "SEED_ADMIN_PASSWORD": E2E_PASSWORD,
    "SEED_AGENT_PASSWORD": E2E_PASSWORD,
    "SEED_CUSTOMER_PASSWORD": E2E_PASSWORD,
})

from contextlib import asynccontextmanager  # noqa: E402

import uvicorn  # noqa: E402

from backend.ai.prompts import ROUTE_TOOL  # noqa: E402
from backend.ai.rules import get_route, get_urgency  # noqa: E402

from backend.database import seed_admin, seed_data  # noqa: E402
from backend.database.session import SessionLocal, init_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.services import uploads  # noqa: E402

uploads.UPLOAD_DIR = _tmp / "uploads"

# 먼저 맞는 단어의 유형 (없으면 기타). 테스트 문장을 고를 때 이 표를 봅니다
KEYWORDS = [
    ("주문 취소", ("취소",)), ("교환", ("교환", "바꿔")), ("반품·환불", ("반품", "환불")),
    ("결제", ("결제", "카드", "입금")), ("쿠폰·적립금·회원", ("쿠폰", "적립금", "포인트", "회원")),
    ("배송", ("배송", "택배", "도착", "안 와")), ("상품", ("사이즈", "재입고", "소재", "색상")),
]


class KeywordAnalyzer:
    """분류 모델 대신 쓰는 가짜 분석기 (화면 흐름 확인용, 정확도와 무관)"""

    def analyze(self, text: str) -> dict:
        category = next((c for c, words in KEYWORDS if any(w in text for w in words)), "기타")
        return {"category": category, "confidence": 0.95, "sentiment": "중립", "sentiment_confidence": 0.9,
                "route": get_route(category), "urgency": get_urgency(category, "중립", text),
                "scores": {}, "model_version": "e2e-keyword"}


class FakeLLM:
    """LLM 대신: 자동 답변은 하지 않고(시험 흐름이 늘 상담원을 거치게) 처리 경로에 맞는 도구로 '답변 초안'.
    예: 주문 취소(접수형) → 티켓 접수 → 취소 티켓이 생겨 상담원이 승인할 수 있음"""
    label = "e2e-fake-llm"

    def json(self, system, user, schema, name, timeout):
        usage = {"input": 0, "output": 0}
        if name == "route":
            m = re.search(r"처리 경로: (\S+)", user)
            tool = ROUTE_TOOL.get(m.group(1) if m else "", "상담원 이관")
            return {"decision": "답변 초안", "tool": tool, "faq_ids": [], "reason": "시험용 판단 (e2e)"}, usage
        text = "안녕하세요, 고객님. 요청하신 내용을 확인했습니다. (시험용 초안)"
        data = {"answer": text, "used_faq_ids": [], "grounded": False}
        if name == "draft":
            data["check_points"] = []
        return data, usage


_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan(a):
    async with _lifespan(a):
        a.state.analyzer = KeywordAnalyzer()
        a.state.llm = FakeLLM()
        yield


app.router.lifespan_context = lifespan


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="화면 자동 테스트용 백엔드")
    p.add_argument("--port", type=int, default=8001)
    args = p.parse_args()

    init_db()
    with SessionLocal() as db:
        seed_admin.seed_accounts(db)
        seed_data.seed_faqs(db)
        seed_data.seed_orders(db, reset=False)
        db.flush()
        seed_admin.seed_customer_passwords(db)
        db.commit()
    print(f"[e2e] 임시 DB: {_tmp}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
