"""OpenAI 호출 (JSON 스키마로 답을 받음). 에이전트의 처리 방식 판단·FAQ 답변에서 씁니다."""

import json

from openai import OpenAI

from backend.core.config import Settings


class LLM:
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY 가 없습니다.")
        # 재시도는 하지 않음: 제한 시간(20초) 안에 끝나지 않으면 상담원 검토로 넘기는 편이 낫다
        self.client = OpenAI(api_key=settings.openai_api_key, max_retries=0)
        self.model = settings.openai_model
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
