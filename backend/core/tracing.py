"""LangSmith 추적 (3주차): 문의마다 LangGraph 단계·LLM 호출·답변 초안을 LangSmith 화면에서 볼 수 있게.

켜는 방법: .env 에 LANGSMITH_TRACING=true, LANGSMITH_API_KEY, (선택) LANGSMITH_PROJECT, LANGSMITH_ENDPOINT
- **서버(backend/main.py)와 평가 스크립트에서 --trace 를 줄 때만** 켭니다 (setup 을 부른 곳만).
  학습 스크립트처럼 AI Hub 데이터를 다루는 코드에서는 켜지지 않습니다 — 추적은 늘 trace() 안에서만,
  enabled 를 명시해서 돌리므로 환경 변수 LANGSMITH_TRACING 이 남아 있어도 따라가지 않습니다.
- **개인정보 가리기:** LangSmith로 보내기 전에 이메일·전화번호·주문번호·운송장 번호·카드번호·주민등록번호를 가립니다
  (MASK_RULES). 고객 이름·이메일은 처음부터 처리 흐름에 넣지 않습니다.
- 테스트(conftest.py)는 LANGSMITH_TRACING=false 로 끕니다.
"""

import logging
import uuid
import warnings
from contextlib import contextmanager
from types import SimpleNamespace

logger = logging.getLogger("inquai")

MASK_RULES = [  # 순서 중요: 긴 숫자 패턴부터
    {"pattern": r"[\w.+-]+@[\w-]+\.[\w.-]+", "replace": "<이메일>"},
    {"pattern": r"\b\d{6}-?[1-4]\d{6}\b", "replace": "<주민등록번호>"},
    {"pattern": r"\b\d{4}-?\d{4}-?\d{4}-?\d{4}\b", "replace": "<카드번호>"},
    # 주문번호 (문의 번호 INQ-20261117-0003 은 가리지 않음: 추적 기록을 문의 번호로 찾아야 해서)
    {"pattern": r"(?<!INQ-)\b\d{8}-\d{4}\b", "replace": "<주문번호>"},
    {"pattern": r"\b0\d{1,2}-?\d{3,4}-?\d{4}\b", "replace": "<전화번호>"},
    {"pattern": r"\b\d{10,14}\b", "replace": "<운송장번호>"},
]

_state = SimpleNamespace(client=None, project=None, project_id=None)


def mask(value):
    """MASK_RULES 로 문자열(또는 dict·list 안의 문자열)을 가림 (LangSmith anonymizer와 같은 규칙)"""
    from langsmith.anonymizer import create_anonymizer

    return create_anonymizer(MASK_RULES)(value)


def setup(settings) -> bool:
    """설정에서 추적이 켜져 있고 키가 있으면 LangSmith 클라이언트를 준비. 켜졌는지 돌려줌"""
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        return False
    from langsmith import Client
    from langsmith.anonymizer import create_anonymizer

    _state.client = Client(api_url=settings.langsmith_endpoint or None, api_key=settings.langsmith_api_key,
                           anonymizer=create_anonymizer(MASK_RULES))
    _state.project = settings.langsmith_project
    logger.info("LangSmith 추적 켜짐 (프로젝트 %s, 개인정보 가림)", _state.project)
    return True


def enabled() -> bool:
    return _state.client is not None


@contextmanager
def trace(metadata: dict | None = None, tags: list[str] | None = None):
    """이 안에서 돈 LangGraph·LLM·@traceable 함수를 LangSmith에 기록 (켜져 있지 않으면 아무것도 보내지 않음)"""
    from langsmith import tracing_context

    with tracing_context(enabled=enabled(), client=_state.client, project_name=_state.project,
                         metadata=metadata or {}, tags=tags or []):
        yield


def new_run_id() -> uuid.UUID:
    return uuid.uuid4()


def run_url(run_id) -> str | None:
    """LangSmith 화면 주소 (AI 실행 기록의 '추적 보기' 링크). 실패해도 처리에는 영향 없음"""
    if not enabled():
        return None
    try:
        c = _state.client
        if _state.project_id is None:
            try:
                _state.project_id = c.read_project(project_name=_state.project).id
            except Exception:  # noqa: BLE001  처음이면 프로젝트가 아직 없음
                _state.project_id = c.create_project(_state.project).id
        with warnings.catch_warnings():  # get_run_url 은 2027-01 이후 바뀜 (그때 client.runs.get_url 로)
            warnings.simplefilter("ignore")
            return c.get_run_url(run=SimpleNamespace(id=run_id), project_id=_state.project_id)
    except Exception:  # noqa: BLE001
        logger.warning("LangSmith 링크를 만들지 못했습니다.", exc_info=True)
        return None


def flush() -> None:
    if enabled():
        try:
            _state.client.flush()
        except Exception:  # noqa: BLE001
            logger.warning("LangSmith 전송을 마치지 못했습니다.", exc_info=True)
