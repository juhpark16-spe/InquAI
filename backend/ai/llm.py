"""LLM 호출 (JSON 스키마로 답을 받음). 에이전트의 처리 방식 판단·FAQ 답변·초안·표기 재확인에서 씁니다.

OpenAI와 Gemini 모두 OpenAI 라이브러리로 부릅니다 (Gemini는 OpenAI 호환 주소, .env 의 LLM_PROVIDER=gemini).
"""

import json

from openai import OpenAI

from backend.core.config import Settings, llm_connection


class LLM:
    def __init__(self, settings: Settings, patient: bool = False):
        """patient: 평가·학습 스크립트용. 요청 수 제한(429)·일시 오류면 OpenAI 라이브러리가 기다렸다가 다시 보냄 (최대 6번).
        서버는 다시 보내지 않음 (문의 1건 20초 제한 안에서 끝나지 않으면 상담원 검토가 나음)"""
        key, model, base_url = llm_connection(settings)
        if not key:
            raise RuntimeError(f"{settings.llm_provider} API 키가 없습니다 (.env).")
        # 재시도는 하지 않음: 제한 시간(20초) 안에 끝나지 않으면 상담원 검토로 넘기는 편이 낫다
        # wrap_openai: LangSmith 추적이 켜진 곳(tracing.trace 안)에서만 프롬프트·응답·토큰을 기록, 아니면 그냥 통과
        from langsmith.wrappers import wrap_openai

        self.client = wrap_openai(OpenAI(api_key=key, base_url=base_url, max_retries=6 if patient else 0))
        self.model = model
        self.effort = settings.llm_reasoning_effort
        self.label = f"{self.model} (reasoning_effort={self.effort})"

    def json(self, system: str, user: str, schema: dict, name: str, timeout: float) -> tuple[dict, dict]:
        """(결과, 토큰 수). 시간 초과·API 오류는 예외로 올라갑니다."""
        resp = self.client.chat.completions.create(
            model=self.model, reasoning_effort=self.effort, timeout=timeout,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        )
        usage = {"input": resp.usage.prompt_tokens, "output": resp.usage.completion_tokens} if resp.usage else {}
        return json.loads(resp.choices[0].message.content), usage
