"""LangSmith 추적: 개인정보 가리기, 기본은 꺼짐 (테스트·스크립트에서 아무것도 보내지 않음)"""

from types import SimpleNamespace

from backend.core import tracing


def test_mask_rules():
    text = ("메일 hong.gil@example.com 전화 010-1234-5678 / 01012345678 주문번호 20261112-0005 "
            "운송장 336070141120 카드 1234-5678-9012-3456 주민 900101-1234567 금액 39,000원 날짜 2026-11-17")
    masked = tracing.mask(text)
    for secret in ("hong.gil@example.com", "010-1234-5678", "01012345678", "20261112-0005", "336070141120",
                   "1234-5678-9012-3456", "900101-1234567"):
        assert secret not in masked
    for kept in ("39,000원", "2026-11-17"):                       # 금액·날짜는 그대로 (판단에 필요)
        assert kept in masked
    assert tracing.mask("문의 INQ-20261117-0003 주문 20261117-0003") == "문의 INQ-20261117-0003 주문 <주문번호>"
    assert tracing.mask({"messages": [{"content": "010-1111-2222"}]}) == {"messages": [{"content": "<전화번호>"}]}


def test_tracing_is_off_without_explicit_setup(client):
    assert tracing.enabled() is False                             # 테스트: LANGSMITH_TRACING=false
    assert tracing.run_url(tracing.new_run_id()) is None
    off = SimpleNamespace(langsmith_tracing=True, langsmith_api_key="", langsmith_project="p", langsmith_endpoint="")
    assert tracing.setup(off) is False                            # 키가 없으면 켜지지 않음
    with tracing.trace(metadata={"inquiry_number": "X"}):         # 꺼져 있어도 안에서 정상 동작
        pass


def test_trace_link_opens_the_inquai_project():
    """옛 형식(.../r/{실행})은 LangSmith 화면이 못 알아봐서 다른 프로젝트로 감 → 프로젝트 주소 + peek 로"""
    old = "https://smith.langchain.com/o/t1/projects/p/263d-00a1/r/5a88-00b2?poll=true"
    assert tracing.trace_link(old) == "https://smith.langchain.com/o/t1/projects/p/263d-00a1?peek=5a88-00b2&peeked_trace=5a88-00b2"
    assert tracing.trace_link(None) is None
    new = "https://smith.langchain.com/o/t1/projects/p/263d-00a1?peek=5a88-00b2"
    assert tracing.trace_link(new) == new
