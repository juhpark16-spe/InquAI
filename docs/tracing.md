# LangSmith 추적

문의마다 에이전트가 거친 단계(LangGraph 노드), LLM에 보낸 프롬프트·받은 응답·토큰, 답변 초안 작성을
LangSmith 화면에서 볼 수 있게 했습니다. 구현: `backend/core/tracing.py`

## 켜는 방법

`.env` (값은 `.env.example` 참고)

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...        # smith.langchain.com → Settings → API Keys
LANGSMITH_PROJECT=inquai     # 기록이 쌓일 프로젝트 이름
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

- **서버에서만 켜집니다** (`backend/main.py`가 시작할 때 `tracing.setup`). 평가는 `--trace`를 줄 때만 (프로젝트 `inquai-eval`).
  학습 스크립트(감정 라벨링, Zero-shot 비교 등 **AI Hub 데이터**를 다루는 코드)는 `.env`를 읽어도 추적되지 않습니다.
  추적은 늘 `tracing.trace()` 안에서 켜짐/꺼짐을 명시해서 돌기 때문입니다.
- 테스트는 `LANGSMITH_TRACING=false`로 끕니다 (`backend/tests/conftest.py`).

## 무엇이 기록되나

| 기록 (루트) | 언제 | 안에 있는 것 |
| --- | --- | --- |
| 문의 처리 | 문의 등록 | LangGraph 노드(FAQ 검색 → 규칙 판단 → LLM 판단 → 주문 본인 확인 → 도구 → 답변 검사), LLM 호출(ChatOpenAI) |
| 답변 초안 작성 | 고객 응답 뒤 / 상담원 [AI 초안 만들기] | 초안 LLM 호출, 결과(초안·확인할 것) |

- 메타데이터 `inquiry_number`로 같은 문의의 기록을 묶어 찾습니다 (태그: 문의 처리 / 답변 초안 / 응답 뒤 / 상담원 요청).
- 문의 상세 → AI 처리 상세 → **"LangSmith에서 단계별로 보기"** 링크 (`agent_logs.trace_url`).

## 개인정보 가리기

LangSmith로 보내기 전에 아래를 가립니다 (`MASK_RULES`, 입력·출력·메타데이터 모두).

| 대상 | 예 | 바뀐 모양 |
| --- | --- | --- |
| 이메일 | test.me@example.com | `<이메일>` |
| 전화번호 | 010-2222-3333, 01022223333 | `<전화번호>` |
| 주문번호 | 20261112-0005 | `<주문번호>` (문의 번호 INQ-…는 그대로) |
| 운송장 번호 (10~14자리) | 336070141120 | `<운송장번호>` |
| 카드번호, 주민등록번호 | | `<카드번호>`, `<주민등록번호>` |

- 고객 이름·이메일은 처음부터 처리 흐름에 넣지 않습니다. DB 세션·문의 객체도 기록하지 않습니다 (초안은 문의 번호만).
- 확인 (2026-11-17): 전화번호·이메일을 적은 시연 문의 2건을 등록해 기록 11개를 확인했고, 원래 값은 하나도 남지 않았습니다.
- 고객 화면 개인정보 안내에 "처리 기록이 외부 서비스(LangSmith)에 보관될 수 있으며 이메일·전화번호·주문번호 등은 가려서 보냄"을 추가했습니다.
- LangSmith 무료 플랜: 한 달 5,000개 기록, 14일 보관.
