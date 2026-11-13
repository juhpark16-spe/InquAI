# API 명세 초안

기획서 v2 6장(로그인·보안)과 7장(주요 API)을 바탕으로 요청·응답 형식, 권한, 오류를 구체화한 초안입니다.
테이블 구조는 `docs/db_schema.md`를 따릅니다. 2주차에 FastAPI로 옮기면 Swagger(`/docs`)가 실제 명세가 됩니다.

## 1. 공통 규칙

### 주소와 형식
- 기본 주소: `/api` (개발: `http://localhost:8000/api`)
- 요청·응답 본문은 JSON, 날짜는 ISO 8601 UTC (`2026-11-13T05:30:00Z`)
- 라우터: **Auth API**(`/api/auth`) / **Customer API**(문의·관리 기능 전부)

### 인증 (기획서 6장)
| 쿠키 | HttpOnly | 유효 | 내용 |
| --- | --- | --- | --- |
| `access_token` | O | 30분 | JWT (`sub`=사용자 id, `role`, `exp`) |
| `refresh_token` | O | 7일 | JWT (`sub`, `jti`). `jti`를 `refresh_tokens` 테이블에 기록 |
| `csrf_token` | **X** (React가 읽음) | access와 같음 | 무작위 문자열 |

- 모든 쿠키: `SameSite=Lax`, `Secure`(개발 환경에서는 `.env`의 `COOKIE_SECURE=false`로 끔), `Path=/api`
- **CSRF:** 로그인이 필요한 POST·PUT·PATCH·DELETE 요청은 헤더 `X-CSRF-Token`에 `csrf_token` 쿠키 값을 넣어야 합니다. 값이 다르면 403.
- React: Axios `withCredentials: true`, 요청 인터셉터에서 `X-CSRF-Token` 헤더 추가, 401을 받으면 `/api/auth/refresh` 한 번 시도 후 실패하면 로그인 화면으로 이동

### 권한 표기
| 표기 | 의미 |
| --- | --- |
| 공개 | 로그인 없이 호출 (고객 화면) |
| 로그인 | 관리자·상담원 모두. **상담원은 자신에게 배정된 문의만** (아니면 403) |
| 관리자 | 관리자만 |
| 내부 | 에이전트가 서버 안에서 호출하는 도구. HTTP로는 관리자만 (Swagger 테스트용) |

### 오류 응답
```json
{ "detail": "로그인이 필요합니다.", "code": "AUTH_REQUIRED" }
```
| 상태 | code 예시 | 언제 |
| --- | --- | --- |
| 400 | `INVALID_STATE` | 상태상 할 수 없는 작업 (이미 완료된 답변 승인 등) |
| 401 | `AUTH_REQUIRED`, `TOKEN_EXPIRED`, `LOGIN_FAILED` | 로그인 안 함, 토큰 만료, 아이디·비밀번호 틀림 |
| 403 | `FORBIDDEN`, `CSRF_FAILED` | 권한 부족, 배정되지 않은 문의, CSRF 토큰 불일치 |
| 404 | `NOT_FOUND` | 없는 자원. **고객 조회는 번호가 틀려도 이메일이 틀려도 같은 404** (다른 사람 문의 존재 여부를 알 수 없게) |
| 422 | (FastAPI 기본) | 입력 형식 오류 (Pydantic) |
| 423 | `ACCOUNT_LOCKED` | 로그인 5회 실패로 15분 잠김. `locked_until` 함께 반환 |
| 429 | `TOO_MANY_REQUESTS` | 공개 API 과다 호출 (아래) |

### 목록 공통 파라미터
`page`(기본 1), `size`(기본 20, 최대 100). 응답: `{ "items": [...], "total": 132, "page": 1, "size": 20 }`

## 2. Auth API

### POST /api/auth/login — 로그인 (공개)
```json
// 요청
{ "username": "admin", "password": "••••" }
// 200 응답 + Set-Cookie: access_token, refresh_token, csrf_token
{ "user": { "id": 1, "username": "admin", "display_name": "관리자", "role": "admin" } }
```
- 실패하면 `failed_login_count`를 올리고, 5회째에 `locked_until = 지금 + 15분` → 423
- 잠금 시각이 지나면 자동 해제. 성공하면 실패 횟수 0
- 성공·실패 모두 `admin_audit_logs`에 기록 (login / login_failed)
- 아이디가 없을 때와 비밀번호가 틀릴 때 같은 메시지: "아이디 또는 비밀번호가 올바르지 않습니다."

### POST /api/auth/refresh — Access Token 재발급 (refresh_token 쿠키)
- 기존 `jti`를 무효화(`revoked_at`)하고 새 refresh_token을 발급 (토큰 회전)
- 무효화된 토큰으로 요청하면 401 → 다시 로그인

### POST /api/auth/logout — 로그아웃 (로그인)
- 세 쿠키 삭제, refresh_token의 `jti` 무효화. 응답 204

### GET /api/auth/me — 내 정보 (로그인)
```json
{ "id": 2, "username": "agent1", "display_name": "김상담", "role": "agent" }
```

## 3. 고객 API (공개)

### POST /api/inquiries — 문의 등록 → 분석 → 에이전트 처리
```json
// 요청
{
  "customer_name": "홍길동",
  "customer_email": "hong@example.com",
  "order_number": "20261103-0042",      // 선택
  "title": "배송 문의",
  "content": "지금 주문하면 보통 며칠 만에 받을 수 있어요?"
}
// 201 응답 — 자동 답변
{
  "inquiry_number": "INQ-20261113-0007",
  "status": "자동 처리",
  "answer": "결제 완료 후 평일 오후 2시 이전 주문은 당일 출고되고, ...",
  "message": "문의 번호와 이메일로 처리 상태를 다시 확인하실 수 있습니다."
}
// 201 응답 — 답변 초안 / 담당자 연결 (고객에게 분석 결과·판단 이유는 보여주지 않음)
{
  "inquiry_number": "INQ-20261113-0008",
  "status": "검토 대기",          // 또는 "담당자 처리"
  "answer": null,
  "message": "문의가 접수되었습니다. 담당자가 확인 후 답변드리겠습니다."
}
```
**서버 처리 순서**
1. `inquiries` 저장 (status = 접수), 문의 번호 발급
2. 분류 모델: 유형·감정·확신도 → 규칙: 처리 경로·긴급도 (`rules.py`) → `analysis_results` 저장
3. 에이전트: 규칙 판단(확신도 0.8 미만, 긴급도 높음, 기타 → 담당자 연결) 또는 LLM 판단 → 도구 실행 → 자동 답변이면 FAQ 근거 답변 생성 (`prompts.py`)
4. `responses`, `tickets`, `agent_logs` 저장, `inquiries.status` 갱신

- **동기 방식** (11장 결정 사항): 분석과 에이전트 처리가 끝난 뒤 응답합니다. 분석은 1초 이내, LLM 판단·답변까지 최대 8~10초 (프롬프트 검증 기준). 화면에 "답변을 작성하고 있습니다" 표시가 필요합니다.
- **실패 처리:** LLM 오류나 20초 초과 시 자동 답변 없이 `검토 대기`로 저장하고 `agent_logs.error`에 기록합니다. 고객 응답은 위의 "접수되었습니다" 형식입니다.
- **주문번호가 있으면** 배송 조회·티켓 접수 전에 주문의 고객 이메일과 `customer_email`이 같은지 확인합니다. 다르면 도구를 실행하지 않고 `담당자 처리`로 보냅니다 (기획서 2-4).
- **입력 제한:** content 5~2,000자, title 1~200자, 이메일 형식 확인. 같은 IP에서 1분에 5건 초과 시 429.

### POST /api/inquiries/lookup — 본인 문의 조회
```json
// 요청
{ "inquiry_number": "INQ-20261113-0008", "customer_email": "hong@example.com" }
// 200 응답
{
  "inquiry_number": "INQ-20261113-0008",
  "title": "배송 문의",
  "content": "...",
  "status": "완료",
  "answer": "주문하신 패딩은 현재 대전 HUB에 도착해 ...",   // 발송된 답변만 (초안은 보이지 않음)
  "created_at": "...", "answered_at": "..."
}
```
- 번호와 이메일이 모두 맞을 때만 200. 하나라도 틀리면 404 (같은 메시지)
- 같은 IP에서 1분에 10회 초과 시 429 (번호 추측 방지)

## 4. 문의 관리 API (로그인)

### GET /api/inquiries — 문의 목록
| 파라미터 | 예 | 설명 |
| --- | --- | --- |
| category | 배송 | 8개 유형 |
| urgency | 높음 | |
| status | 검토 대기 | |
| decision | 답변 초안 | 처리 방식 |
| assigned_to | 2 / `me` / `none` | 관리자만 다른 사람 지정 가능 |
| q | 환불 | 제목·내용·문의 번호·이메일 검색 |
| sort | `urgency` (기본) / `-created_at` | 긴급도 높은 순 → 최신순 |

상담원이 호출하면 `assigned_to=me`가 강제됩니다.
```json
{ "items": [ {
    "id": 8, "inquiry_number": "INQ-20261113-0008", "title": "배송 문의", "customer_name": "홍길동",
    "status": "검토 대기", "category": "배송", "urgency": "낮음", "sentiment": "중립",
    "decision": "답변 초안", "assigned_to": { "id": 2, "display_name": "김상담" }, "created_at": "..."
  } ], "total": 1, "page": 1, "size": 20 }
```

### GET /api/inquiries/{id} — 문의 상세
```json
{
  "id": 8, "inquiry_number": "INQ-20261113-0008",
  "customer": { "name": "홍길동", "email": "hong@example.com", "order_number": "20261103-0042" },
  "title": "배송 문의", "content": "11월 10일에 주문한 패딩이 아직 안 왔어요...",
  "status": "검토 대기", "assigned_to": null,
  "analysis": {
    "category": "배송", "confidence": 0.93, "sentiment": "중립", "sentiment_confidence": 0.81,
    "urgency": "낮음", "route": "조회형",
    "decision": "답변 초안", "decided_by": "LLM",
    "decision_reason": "특정 주문의 배송 위치 확인이 필요합니다.",
    "scores": { "category": { "배송": 0.93, "상품": 0.01 }, "sentiment": { "중립": 0.81 } },
    "model_version": "category_ev_s123"
  },
  "responses": [ { "id": 5, "draft_text": "...", "final_text": null, "status": "초안",
                   "used_faq_ids": [], "grounded": null } ],
  "tickets": [],
  "agent_logs": [ { "selected_tool": "배송 조회", "tool_success": true,
                    "tool_output": { "shipping_status": "대전 HUB 도착" }, "latency_ms": 8200 } ],
  "corrections": []
}
```

### PATCH /api/inquiries/{id}/analysis — 분류 결과 수정 (재학습 데이터)
```json
// 요청 (바꿀 것만)
{ "category": "반품·환불", "sentiment": "부정" }
// 200 응답: 바뀐 analysis
```
- 바뀐 항목마다 `label_corrections` 1줄 (원문 복사본 포함), `admin_audit_logs` (label_correct)
- 유형이 바뀌면 `route`, `urgency`를 규칙으로 다시 계산합니다. 에이전트는 다시 실행하지 않습니다.

### PATCH /api/inquiries/{id}/assign — 배정·재배정 (관리자)
```json
{ "assigned_to": 2 }      // null이면 배정 해제
```
- status가 `검토 대기`·`접수`이면 `담당자 처리`로 바꿉니다. audit_logs (assign)

### PATCH /api/inquiries/{id}/status — 상태 변경 (로그인, **추가**)
```json
{ "status": "완료" }
```
- 답변 없이 끝내는 경우(중복 문의, 스팸 등)용. audit_logs (status_change)

## 5. 답변 API (로그인)

### PUT /api/responses/{id} — 답변 초안 수정
```json
{ "final_text": "고객님, 주문하신 패딩은 현재 대전 HUB에 도착해 ..." }
```
- status가 `초안`일 때만 (발송된 답변은 400 `INVALID_STATE`). audit_logs (response_edit)

### POST /api/responses/{id}/approve — 승인·발송
- `final_text`가 없으면 `draft_text`를 그대로 발송
- `is_edited = (final_text != draft_text)`, `approved_by`, `approved_at` 기록
- `responses.status = 발송`, `inquiries.status = 완료`. audit_logs (response_approve)
- 발송은 실제 메일이 아니라 DB 저장입니다. 고객은 `/api/inquiries/lookup`으로 확인합니다.

## 6. 티켓 API

### POST /api/tickets — 티켓 접수 (내부: 에이전트 도구)
```json
{ "inquiry_id": 9, "order_id": 31, "ticket_type": "환불", "reason": "사이즈가 안 맞아 반품" }
```
- `ticket_type`: 환불 / 교환 / 취소 / 이관
- 정책 확인 (`docs/shop_policy.md`): 취소는 출고 전만, 반품·교환은 배송 완료 7일 이내(불량 30일). 조건에 맞지 않아도 접수는 하되 `reason`에 "정책 기간 초과"를 붙여 상담원이 판단합니다.

### GET /api/tickets — 티켓 목록 (로그인)
파라미터: `ticket_type`, `status`. 상담원은 배정된 문의의 티켓만.

### PATCH /api/tickets/{id} — 승인·반려 (로그인, **추가**)
```json
{ "status": "승인", "memo": "택 제거 전 상태 확인" }
```
- audit_logs (ticket_approve / ticket_reject)

## 7. 주문 API

### GET /api/orders/{order_number}/shipping?email= — 배송 조회 (내부: 에이전트 도구)
```json
{ "order_number": "20261103-0042", "product_name": "경량 패딩", "order_status": "배송 중",
  "shipping_status": "대전 HUB 도착", "tracking_number": "6012-3456-7890", "ordered_at": "..." }
```
- `email`이 주문 고객 이메일과 다르면 404 (다른 고객 정보 노출 방지, 기획서 10장 완료 기준)
- 경로 변수는 기획서의 `{order_id}` 대신 고객이 아는 `order_number`를 씁니다.

## 8. FAQ API (관리자)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /api/faqs | 목록. `category`, `q`, `include_inactive` |
| POST | /api/faqs | `{ "code": "F22", "category": "배송", "question": "...", "answer": "..." }` |
| PUT | /api/faqs/{id} | 전체 수정 |
| DELETE | /api/faqs/{id} | 실제로 지우지 않고 `is_active=false` |

- 등록·수정·비활성 후 ChromaDB 색인을 다시 만듭니다 (3주차).
- 답변을 바꿀 때는 `docs/shop_policy.md`와 맞는지 확인합니다.

## 9. 통계·로그 API

### GET /api/stats/summary — 대시보드 (관리자)
파라미터: `from`, `to` (기본: 오늘)
```json
{
  "total": 132, "today": 18,
  "by_category": { "배송": 41, "반품·환불": 22 },
  "by_urgency": { "높음": 9, "보통": 51, "낮음": 72 },
  "by_decision": { "자동 답변": 45, "답변 초안": 60, "담당자 연결": 27 },
  "auto_rate": 0.34,                   // 성공 지표: 자동 처리율 30% 이상
  "pending_review": 12,                // 검토 대기
  "approval_without_edit_rate": 0.72,  // 성공 지표: 답변 초안 승인율 70% 이상
  "avg_latency_ms": 8400
}
```
기획서 7장은 권한이 "필요"이지만, 6장 권한표에 맞춰 관리자만으로 정했습니다.

### GET /api/admin/agent-logs — AI 실행 로그 (관리자, 상담원은 배정된 문의만)
파라미터: `inquiry_id`, `decision`, `selected_tool`, `tool_success`, `from`, `to`
- `decision`: 자동 답변 / 답변 초안 / 담당자 연결
- `selected_tool`: FAQ 검색 / 배송 조회 / 티켓 접수 / 상담원 이관 (값은 `backend/ai/prompts.py`의 `DECISIONS`, `TOOLS`와 같음)
- 성공 지표 "도구 선택 정확도"는 정답 도구를 붙인 테스트 문의(`data/test/prompt_cases.json`)를 등록한 뒤 이 로그의 `selected_tool`과 비교해 계산합니다.

### GET /api/admin/audit-logs — 작업 기록 (관리자)
파라미터: `admin_id`, `action`, `target_type`, `from`, `to`

## 10. 기획서 7장과 달라진 점

| 구분 | 내용 | 이유 |
| --- | --- | --- |
| 추가 | `PATCH /api/inquiries/{id}/status` | 답변 없이 끝내는 문의 처리 |
| 추가 | `PATCH /api/tickets/{id}` | 기획서 2-3 "환불·교환 승인·반려"에 필요한 API가 없었음 |
| 변경 | 배송 조회 경로 `{order_id}` → `{order_number}` + `email` | 고객이 아는 값으로 조회하고, 이메일로 본인 확인 |
| 변경 | `/api/stats/summary` 권한 "필요" → 관리자 | 6장 권한표 (통계 대시보드는 관리자만) |
| 구체화 | 고객 응답에 분석 결과·판단 이유를 넣지 않음 | 내부 정보 노출 방지 |
| 구체화 | 고객 조회 실패는 번호·이메일 구분 없이 404 | 다른 사람 문의 존재 여부 노출 방지 |

## 11. 결정 사항

### 문의 등록은 동기 방식 (2026-11-13 결정)
`POST /api/inquiries`는 분석과 에이전트 처리가 끝난 뒤 결과(자동 답변 또는 접수 안내)를 한 번에 돌려줍니다.

| 항목 | 내용 |
| --- | --- |
| 이유 | 기획서 2-4 "문의 직후 AI 자동 답변 확인"과 8장 시연 흐름(등록하자마자 답변)에 맞음. 백그라운드 방식에 필요한 작업 큐·"처리 중" 상태·폴링을 만들지 않아도 돼서 2주차 최소 버전 일정에 맞음 |
| 예상 대기 시간 | 규칙으로 바로 이관 1초 이내 / LLM 판단 1회(초안·이관) 5~7초 / 자동 답변(판단 + 답변) 8~10초 |
| 시간 제한 | 에이전트 처리 20초. 넘거나 LLM 오류면 자동 답변 없이 "접수되었습니다"로 응답하고 `검토 대기`로 저장, `agent_logs.error` 기록 |
| 서버 구현 | FastAPI `async` 엔드포인트 + OpenAI 비동기 클라이언트(`AsyncOpenAI`). 기다리는 동안 다른 요청을 처리할 수 있음 |
| 문의 보존 | 1단계에서 문의를 먼저 저장하고 문의 번호를 발급하므로, 고객이 기다리다 창을 닫아도 문의는 남고 조회 화면에서 확인 가능 |
| 고객 화면 | 등록 버튼을 누르면 버튼을 잠그고 "답변을 작성하고 있습니다" 로딩 표시 (중복 등록 방지) |
| 나중에 바꾸려면 | 에이전트 처리를 함수 하나(`process_inquiry(inquiry_id)`)로 만들어 두고, 그 함수를 백그라운드 작업으로 돌리면 백그라운드 방식으로 전환 가능 |

### 상담원 역할 유지 (2026-11-13 결정)
관리자(admin)와 상담원(agent) 두 역할을 그대로 둡니다 (기획서 6장 권한표). 상담원은 자신에게 배정된 문의·티켓·실행 로그만 다룰 수 있고, 문의 관련 API에서 역할과 함께 `inquiries.assigned_to`를 확인합니다. 완료 기준 테스트의 "상담원이 다른 상담원에게 배정된 문의 수정 → 403"을 지켜야 합니다.

## 12. 정할 것 (2주차 시작 전)

- **고객 화면의 문의 유형 선택:** 고객이 직접 유형을 고르게 할지 (지금은 모델만 판단)
