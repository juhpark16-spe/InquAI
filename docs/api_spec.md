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
| `csrf_token` | **X** (React가 읽음) | refresh와 같음 (7일) | 무작위 문자열. 로그인·재발급 때마다 새로 만듦 |

- `csrf_token`을 access(30분)와 같게 두면 access가 만료된 뒤 `/api/auth/refresh`를 부를 때 CSRF 값이 없어 재발급할 수 없어서, refresh와 같은 7일로 정했습니다 (2주차 구현 시 변경).

- 모든 쿠키: `SameSite=Lax`, `Secure`(개발 환경에서는 `.env`의 `COOKIE_SECURE=false`로 끔)
- 경로: `access_token`·`refresh_token`은 `Path=/api`(API 요청에만 전송), `csrf_token`은 `Path=/`. React 화면 주소(`/admin/...`)에서 `document.cookie`로 읽어야 하기 때문 (2주차 화면 연결 시 변경)
- **토큰 버전:** access_token에 계정의 `token_version`(`ver`)을 넣고, 비밀번호를 바꾸거나 관리자가 초기화하면 버전을 올려 다른 기기의 로그인을 30분 기다리지 않고 즉시 끊습니다 (2주차 보안 점검 후 추가).
- **로그인 호출 제한:** 같은 IP에서 1분에 10회 초과 시 429. 계정별 5회 잠금과 함께 여러 아이디에 흔한 비밀번호를 넣어 보는 공격을 막습니다.
- **보안 헤더:** 모든 응답에 `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `/api` 응답에는 `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (`backend/core/security_headers.py`). React 화면은 개발 서버(`vite.config.ts`)와 배포 웹 서버에서 같은 헤더를 붙입니다.
- **API 문서:** `/docs`, `/openapi.json`은 `.env`의 `API_DOCS`(기본 true)로 켜고 끕니다. 배포에서는 false.
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
- 성공·실패 모두 `admin_audit_logs`에 기록 (login / login_failed). 실패 이유(`wrong_password`, `unknown_user`, `locked`, `inactive`)와 IP를 `detail`에 남김
- 잠금은 아이디 기준이라, 없는 아이디는 실패 횟수를 세지 않습니다 (기록만 남김)
- 아이디가 없을 때와 비밀번호가 틀릴 때 같은 메시지: "아이디 또는 비밀번호가 올바르지 않습니다."

### POST /api/auth/refresh — Access Token 재발급 (refresh_token 쿠키)
- `X-CSRF-Token` 헤더 필요. 응답은 로그인과 같은 `{ "user": ... }` + 새 쿠키 세 개
- 기존 `jti`를 무효화(`revoked_at`)하고 새 refresh_token을 발급 (토큰 회전)
- 무효화된 토큰으로 요청하면 401 → 다시 로그인. **이미 회전된 토큰이 다시 오면 토큰이 새어 나간 것으로 보고 그 사용자의 refresh_token을 모두 무효화**

### POST /api/auth/logout — 로그아웃 (refresh_token 쿠키)
- 세 쿠키 삭제, refresh_token의 `jti` 무효화. 응답 204
- access_token이 만료된 상태에서도 로그아웃할 수 있게 refresh_token 쿠키로 사용자를 찾습니다. refresh_token 쿠키가 있으면 `X-CSRF-Token` 헤더 필요

### POST /api/auth/change-password — 내 비밀번호 변경 (로그인, 2주차 추가)
```json
{ "current_password": "••••", "new_password": "••••" }   // 200 응답: { "user": {...} } + 새 쿠키
```
- 현재 비밀번호가 틀리거나 새 비밀번호가 지금과 같으면 400 `INVALID_PASSWORD`. 최소 길이 미달은 422
- 바꾸면 그 계정의 refresh_token을 모두 무효화해 다른 기기의 로그인을 끊고, 지금 화면은 새 쿠키로 로그인을 유지합니다. 작업 기록 `password_change` (비밀번호는 기록하지 않음)
- 화면: 상단의 내 이름을 누르면 나오는 "내 계정"(`/admin/account`)
- **비밀번호 최소 길이**는 `.env`의 `PASSWORD_MIN_LENGTH`(기본 8)를 따릅니다. 로컬 시연 환경만 4로 낮춰 `1234`를 씁니다. 배포할 때는 8 이상으로 둡니다.

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
  "order_number": "20261103-0042",      // 선택 (필수로 하지 않음: 주문과 무관한 문의가 많고 고객이 번호를 모르는 경우가 많음.
                                        //  화면에서 배송·취소·교환·반품 같은 내용을 쓰면 입력을 권유)
  "title": "배송 문의",
  "content": "지금 주문하면 보통 며칠 만에 받을 수 있어요?",
  "password": "••••••"                    // 조회 비밀번호 6~64자 (Argon2 해시로 저장)
}
// 201 응답 — 자동 답변
{
  "inquiry_number": "INQ-20261113-0007",
  "status": "자동 처리",
  "answer": "결제 완료 후 평일 오후 2시 이전 주문은 당일 출고되고, ...",
  "message": "이메일과 문의할 때 정한 비밀번호로 처리 상태를 다시 확인하실 수 있습니다."
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
3. 에이전트 (LangGraph, `backend/agents/graph.py`, 그림 `docs/agent_graph.md`): FAQ 검색 → 규칙 판단(확신도 0.8 미만, 긴급도 높음, 기타 → 담당자 연결) 또는 LLM 판단 → 주문 본인 확인 → 도구 실행 → 자동 답변이면 FAQ 근거 답변 생성과 답변 검사 (`prompts.py`)
4. `responses`, `tickets`, `agent_logs` 저장, `inquiries.status` 갱신
5. 사람이 볼 문의(`검토 대기`·`담당자 처리`)는 **자동 배정** (`backend/services/assignment.py`): 활성 상담원 중 담당 유형에 이 문의 유형이 있는 사람 → 없으면 전체 담당(담당 유형을 비운 상담원) → 그중 지금 미처리가 가장 적은 사람. 아무도 없으면 미배정. 작업 기록 `auto_assign`. 관리자는 언제든 재배정 가능

- **동기 방식** (11장 결정 사항): 분석과 에이전트 판단이 끝난 뒤 응답합니다. 분석은 1초 이내, LLM 판단·자동 답변까지 보통 5~8초 (`docs/agent_eval.md`). 화면에 "답변을 작성하고 있습니다" 표시가 필요합니다.
- **답변 초안은 응답 뒤에** (3주차): '답변 초안'으로 판단하면 고객에게 바로 접수 안내를 보내고, 초안은 FastAPI BackgroundTasks로 그 뒤에 씁니다 (`backend/services/drafts.py`). 결과는 `responses`(초안)와 `agent_logs`(초안 글·토큰, 실패하면 `error = 초안 작성 실패 …`)에 남습니다.
- **실패 처리:** LLM 오류나 20초 초과 시 자동 답변 없이 `검토 대기`로 저장하고 `agent_logs.error`에 기록합니다. 고객 응답은 위의 "접수되었습니다" 형식입니다.
- **주문번호가 있으면** 배송 조회·티켓 접수 전에 주문의 고객 이메일과 `customer_email`이 같은지 확인합니다. 다르면 도구를 실행하지 않고 `담당자 처리`로 보냅니다 (기획서 2-4).
- **입력 제한:** content 5~2,000자, title 1~200자, 이메일 형식 확인. 같은 IP에서 1분에 5건 초과 시 429.
- **구현** (`backend/services/inquiries.py`, `backend/agents/pipeline.py` → `graph.py`):
  - 처리 흐름은 위 순서대로 동작하고, FAQ 검색은 KURE-v1 임베딩 + ChromaDB입니다 (모델을 못 불러오면 TF-IDF로 대신, docs/faq_search_eval.md).
  - `agent_logs.steps`에 지나간 그래프 노드(예: FAQ 검색 → 규칙 판단 → LLM 판단 → 주문 본인 확인 → 티켓 접수)를 남겨 상세 화면 'AI 실행 기록'에 보여 줍니다.
  - 티켓 접수는 주문번호가 있을 때만 만들고, 없으면 `tool_success=false`로 남겨 상담원이 고객에게 확인합니다.
  - 분류 모델이 준비되지 않았으면 503 `MODEL_NOT_READY`.

### POST /api/inquiries/lookup — 내 문의 조회 (이메일 + 조회 비밀번호)
```json
// 요청
{ "customer_email": "hong@example.com", "password": "••••••" }
// 200 응답: 이메일이 같고 비밀번호가 맞는 문의만, 최신순
{ "items": [ {
    "inquiry_number": "INQ-20261113-0008",
    "title": "배송 문의",
    "content": "...",
    "status": "완료",
    "answer": "주문하신 패딩은 현재 대전 HUB에 도착해 ...",   // 마지막으로 보낸 답변 (초안은 보이지 않음)
    "created_at": "...", "answered_at": "...",
    "answers": [ { "text": "...", "answered_at": "...", "by": "AI 상담원" },   // 보낸 답변 전부, 시간순 (대화형 화면)
                 { "text": "...", "answered_at": "...", "by": "상담원" } ]     // 상담원 이름은 고객에게 알리지 않음
} ] }
```
- 고객이 문의 번호를 기억하지 않아도 되도록 2주차에 "문의 번호 + 이메일"에서 바꿨습니다. 문의 번호는 계속 발급하고 화면에 보여 줍니다.
- 비밀번호는 문의마다 저장합니다. 같은 이메일이라도 비밀번호가 다른 문의는 보이지 않아, 남이 내 이메일로 문의해도 내 문의는 볼 수 없습니다.
- 일치하는 문의가 없으면 이메일이 없든 비밀번호가 틀리든 같은 404. 이메일이 없을 때도 비밀번호 확인을 한 번 해서 응답 시간으로 구분할 수 없게 합니다.
- 같은 이메일로 15분 안에 5번 틀리면 15분 동안 429 (비밀번호 맞히기 방지, 서버 메모리 기록). 같은 IP 1분 10회 초과도 429
- 한 이메일에서 최근 30건까지 확인합니다. 비밀번호는 되찾을 수 없어, 화면에서 "새 문의에 이전 문의 내용을 적어 달라"고 안내합니다.

### 실제 쇼핑몰 고객센터 기능 (2주차 추가)

| 기능 | API | 내용 |
| --- | --- | --- |
| 개인정보 동의 | `POST /api/inquiries` 의 `privacy_agreed` | 반드시 `true` (빼거나 false 면 422). 동의 시각을 `inquiries.privacy_agreed_at`에 저장. 화면에 수집 항목·목적·보관 기간(3년, 전자상거래법)·외부 AI 처리 안내 |
| 사진 올리기 | `POST /api/inquiries/uploads` (multipart `file`) → `{ token, filename, size }` | JPG·PNG·WEBP만 (파일 앞부분으로 형식 확인, 확장자는 믿지 않음), 1장 5MB, 문의당 3장, IP 1분 10회. 저장 이름은 무작위, `data/uploads/`(Git 제외) |
| 사진 연결 | `POST /api/inquiries` 의 `attachment_tokens: [token]` | 올린 뒤 1시간 안, 한 번만 연결 가능. 잘못되면 문의도 저장하지 않음 |
| 답변 평가 | `POST /api/inquiries/answers/{response_id}/rating?inquiry_number=` `{ customer_email, password, helpful }` | 본인 확인 후 `responses.rating` = 1 / -1 (다시 누르면 변경). 대시보드 "AI 자동 답변 만족도" |
| 추가 문의 | `POST /api/inquiries/follow-up` `{ customer_email, password, inquiry_number, content, attachment_tokens }` | 같은 문의에 이어서. 자동 처리·완료된 문의는 `담당자 처리`로 다시 열고, 미배정이면 자동 배정. AI 재분석은 하지 않음. 문의당 10개까지, IP 1분 5회 |
| 답변 시간 안내 | `/lookup` 응답의 `notice` | "영업일 기준 1일 이내에 답변드립니다 (평일 10:00~17:00)" |
| 답변 알림 | (자동) | 자동 답변·상담원 발송 때 "답변이 등록되었습니다" 이메일을 `notifications`에 **기록만** 함 (메일 서버 없음, 시연용). 본문에 답변 내용은 넣지 않음 |

- 추가 문의·평가도 조회와 같은 잠금(같은 이메일 15분 5회 실패)을 씁니다.
- `/lookup` 응답 항목에 `answers[].id`, `answers[].rating`, `messages`(추가 문의), `attachment_count`, `attachments`, `can_follow_up`이 추가됐습니다.
- **고객이 자기 사진 보기:** 고객은 로그인 쿠키가 없어 `<img>`로 사진을 부를 때 본인 확인을 할 수 없습니다. 그래서 본인 확인(이메일 + 비밀번호)을 통과한 `/lookup` 응답에만 `attachments[].url`로 **30분짜리 서명 주소**(`GET /api/inquiries/attachments/{id}?exp=&sig=`, JWT 키로 HMAC 서명)를 넣어 줍니다. 서명이 틀리거나 시간이 지나면 404

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
    "model_version": "category_aug_s42"
  },
  "responses": [ { "id": 5, "draft_text": "...", "final_text": null, "status": "초안",
                   "used_faq_ids": [], "grounded": null } ],
  "tickets": [],
  "agent_logs": [ { "selected_tool": "배송 조회", "tool_success": true,
                    "tool_output": { "shipping_status": "대전 HUB 도착" }, "latency_ms": 8200 } ],
  "corrections": [],
  // 2주차 추가: 한 화면에서 판단·처리하기 위한 업무 정보 (backend/services/inquiry_context.py)
  "order": { "found": true, "order_number": "20261103-0042", "email_match": true, "product_name": "...",
             "amount": 59000, "order_status": "배송 완료", "shipping_status": "...", "tracking_number": "...",
             "ordered_at": "...", "delivered_at": "...", "cancellable": false,
             "return_until": "...", "returnable": true, "defect_return_until": "..." },   // 주문번호 없으면 null
  "customer_history": [ { "id": 3, "inquiry_number": "...", "title": "...", "status": "완료", "created_at": "..." } ],
  "faq_titles": { "F17": "반품 배송비는 얼마인가요?" },
  "history": [ { "at": "...", "actor": "AI", "text": "담당자 연결 판단 (규칙) · 상담원 이관" } ]
}
```
- `order`: 취소 가능(출고 전), 반품 기한(배송 완료 + 7일, 불량·오배송 30일)을 정책 기준으로 계산. `email_match=false`면 주문자와 문의자가 다를 수 있어 화면에 경고
- `email_orders`: 문의 이메일과 같은 이메일로 주문한 내역 최근 5건 (`order`의 주문은 제외, 각 항목은 `order`와 같은 형식). 주문번호를 적지 않은 문의도 어떤 주문인지 짐작할 수 있게 함. 문의 이메일은 본인 인증 전이라 화면에 "본인 확인 후 안내" 경고를 함께 표시하며, 관리자 화면에만 보이고 고객에게는 나가지 않음
- `customer_history`: 같은 이메일의 다른 문의 최근 5건. 상담원은 자신에게 배정된 것만
- `history`: 접수 → AI 판단 → 자동 배정·답변 발송 → 사람의 배정·상태 변경 (시간순)
- 추가 필드: `due_at`·`overdue`(답변 기한: 긴급 4시간, 그 외 24시간), `messages`(고객 추가 문의), `notes`(내부 메모), `attachments`(사진 목록, token 은 내보내지 않음), `notifications`(알림 기록), `responses[].rating`

### 내부 메모·첨부 사진·기한 (2주차 추가)
| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | /api/inquiries/{id}/notes | `{ "text": "택배사 확인 중" }` 상담원 내부 메모. 고객 API에는 절대 나가지 않음. audit `note_create` |
| GET | /api/inquiries/{id}/attachments/{attachment_id} | 사진 보기 (로그인, 상담원은 배정된 문의만). 저장 때 확인한 형식으로만 응답, `nosniff` |
| GET | /api/inquiries?overdue=true | 답변 기한을 넘긴 미처리만. 목록 항목에도 `due_at`, `overdue` |

- 대시보드 `now.overdue_open`(기한 초과 미처리), `ratings.ai / ratings.agent`(👍·👎 수와 만족도) 추가

### PATCH /api/inquiries/{id}/analysis — 분류 결과 수정 (재학습 데이터, 3주차 구현)
```json
// 요청 (바꿀 것만)
{ "category": "반품·환불", "sentiment": "부정" }
// 200 응답: 바뀐 analysis
```
- 권한은 문의와 같습니다 (관리자 전체, 상담원은 배정된 문의만). 화면: 문의 상세 "AI 분석" 카드의 **[분류 고치기]**
- 값: `category` 8개 유형, `sentiment` 긍정 / 중립 / 부정 (`backend/training/labels.py`). 둘 다 없으면 422
- 바뀐 항목마다 `label_corrections` 1줄 (원문 복사본 포함), `admin_audit_logs` (label_correct, 바뀐 값과 규칙 재계산 결과)
- 유형·감정이 바뀌면 `route`, `urgency`를 규칙으로 다시 계산합니다 → 답변 기한(긴급 4시간)도 따라 바뀝니다.
  모델 확신도·점수는 모델이 낸 값 그대로 둡니다. 에이전트·답변은 다시 실행하지 않습니다.
- 지금과 같은 값만 보내면 400 `NO_CHANGE`, AI 분석이 없는 문의는 400 `NO_ANALYSIS`
- 처리 이력: "분류 수정: 유형 배송 → 반품·환불 · 긴급도 낮음 → 높음" (kind `correct`)
- 대시보드 `ai.corrections`: 기간 안 수정 건수 (유형·감정), AI가 고른 유형별 수정 수 (`by_category`, 모델이 자주 틀리는 유형)
- 재학습용 내보내기: `python -m backend.training.export_corrections` → `data/corrections/{category,sentiment}_corrections.csv`
  (text + 정답 라벨 + 처음 모델 라벨. 고객 원문이 있어 Git 제외)

### PATCH /api/inquiries/{id}/assign — 배정·재배정 (관리자)
```json
{ "assigned_to": 2 }      // null이면 배정 해제
```
- status가 `검토 대기`·`접수`이면 `담당자 처리`로 바꿉니다. audit_logs (assign)
- 없는 계정·비활성 계정에 배정하면 400 `INVALID_ASSIGNEE`. 배정자와 상태가 그대로면 기록하지 않습니다.
- 응답: `{ "id", "inquiry_number", "status", "assigned_to": {id, display_name} | null, "updated_at" }` (상태 변경도 같음)

### PATCH /api/inquiries/{id}/status — 상태 변경 (로그인, **추가**)
```json
{ "status": "완료" }
```
- 답변 없이 끝내는 경우(중복 문의, 스팸 등)용. audit_logs (status_change)
- 바꿀 수 있는 값: `검토 대기`, `담당자 처리`, `완료` (완료한 문의 다시 열기 포함). `접수`·`자동 처리`는 시스템만 정하므로 422
- 지금과 같은 상태로 바꾸면 400 `INVALID_STATE`. 상담원은 배정된 문의만 (아니면 403)

## 5. 답변 API (로그인, 2주차 구현)

권한은 문의와 같습니다 (관리자 전체, 상담원은 배정된 문의만). 구현: `backend/api/responses.py`

### POST /api/inquiries/{id}/responses — 상담원 직접 작성 (추가)
```json
{ "text": "고객님, 답변이 늦어져 죄송합니다. ...", "send": true }   // send=false 면 초안으로 저장
```
- `generated_by = agent_user`. 보내지 않은 초안이 이미 있으면 409 `DRAFT_EXISTS` (`response_id` 함께 반환, 그 초안을 수정)
- 발송 후에도 추가 답변을 새로 작성할 수 있습니다 (문의 1건에 답변 여러 개). audit_logs (response_create)

### PUT /api/responses/{id} — 답변 초안 수정
```json
{ "text": "고객님, 주문하신 패딩은 현재 대전 HUB에 도착해 ..." }   // final_text 로 저장
```
- status가 `초안`일 때만 (발송된 답변은 400 `INVALID_STATE`). 내용이 바뀌었을 때만 audit_logs (response_edit)

### POST /api/responses/{id}/approve — 승인·발송
- 본문에 `{ "text": "..." }`를 함께 보내면 그 내용으로 고친 뒤 바로 발송 (화면의 [발송] 버튼)
- `final_text`가 없으면 `draft_text`를 그대로 발송
- `is_edited`: **AI 초안(llm)을 고쳐서 보냈는지**. 상담원이 직접 쓴 답변은 항상 false이고, 대시보드 "초안 무수정 승인율"도 AI 초안만 셉니다.
- `approved_by`, `approved_at` 기록, `responses.status = 발송`, `inquiries.status = 완료`. audit_logs (response_approve)
- 발송은 실제 메일이 아니라 DB 저장입니다. 고객은 `/api/inquiries/lookup`(이메일 + 조회 비밀번호)으로 확인합니다.

### POST /api/inquiries/{id}/draft — AI 답변 초안 만들기 (3주차)
```json
{ "replace": false }   // 본문 생략 가능
```
응답: 답변(`ResponseOut`). `status = 초안`, `generated_by = llm`, `check_points = ["택배사 파손 확인 결과", ...]`
- 문의 상세의 **[AI 초안 만들기]** 버튼. 담당자 연결 문의나 추가 문의에도 상담원이 원할 때 씁니다.
  (접수 때 에이전트가 '답변 초안'으로 판단한 문의는 이 버튼 없이 초안이 미리 만들어져 있습니다.)
- 근거: 검색된 FAQ(KURE) 3개 + 본인 확인된 주문 정보(취소 가능 여부, 반품 기한) + 티켓 + 대화(처음 문의·추가 문의·보낸 답변).
  고객 이름·이메일은 OpenAI에 넘기지 않고, 주문자 이메일이 다르면 주문 내용도 넘기지 않습니다 ("본인 확인 필요"만).
- 근거로 알 수 없는 내용은 본문에 `[확인 필요: …]`로 남기고 `check_points`에도 적습니다. 그런 초안은 `grounded = false`.
  화면은 "발송 전에 확인할 것"으로 보여 주고, 표시가 남은 채로 [발송]하면 한 번 더 묻습니다.
- 보내지 않은 초안이 있으면 그 자리에 씁니다 (초안은 항상 하나). 상담원이 고쳤거나 직접 쓴 초안이면 409 `DRAFT_EDITED`
  → 화면에서 확인을 받은 뒤 `replace: true`로 다시 요청합니다.
- 오류: LLM 없음 503 `LLM_UNAVAILABLE`, LLM 오류·시간 초과(20초) 502 `DRAFT_FAILED` (기존 초안은 그대로). 같은 IP 1분 10회.
- audit_logs (`draft_generate`: 근거 FAQ·토큰·처리 시간). 처리 이력에 "AI 초안 만들기 / 다시 만들기"로 보입니다.

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

### GET /api/stats/summary — 대시보드 (관리자, 2주차 구현)
파라미터: `from`, `to` (한국 날짜 `YYYY-MM-DD`, 기본: 최근 7일, 최대 92일)
```json
{
  "range": { "from": "2026-11-09", "to": "2026-11-15", "days": 7 },
  "kpi": {
    "total": 132, "today": 18,
    "auto_rate": 0.34,                   // 성공 지표: 자동 처리율 30% 이상 (자동 처리 / 분석된 문의)
    "approval_without_edit_rate": 0.72   // 성공 지표: 초안 무수정 승인율 70% 이상 (승인 기능 3주차)
  },
  "previous": { "from": "2026-11-02", "to": "2026-11-08", "total": 110,   // 바로 앞 같은 길이 기간 (증감 비교)
                "auto_rate": 0.29, "avg_latency_ms": 9100 },
  "now": { "open": 20, "urgent_open": 3, "review_waiting": 12, "unassigned_open": 5 },  // 기간과 관계없이 현재
  "daily": [ { "date": "2026-11-15", "total": 18, "open": 6, "done": 12, "auto": 7,
               "by_category": { "배송": 5, "주문 취소": 1, "...": 0 } } ],
  "by_status": { "접수": 0, "자동 처리": 45, "검토 대기": 12, "담당자 처리": 8, "완료": 67 },
  "by_category": { "배송": 41, "...": 0 },          // 8개 유형 순서 고정 (그래프 색 순서)
  "by_urgency": { "높음": 9, "보통": 51, "낮음": 72 },
  "by_decision": { "자동 답변": 45, "답변 초안": 60, "담당자 연결": 27 },
  "by_decided_by": { "규칙": 40, "LLM": 92 },
  "ai": { "avg_latency_ms": 8400, "low_confidence": 3, "llm_calls": 180,
          "tokens": { "input": 120000, "output": 45000 }, "errors": 1 },
  "staff": [ { "id": 2, "display_name": "상담원 김하늘", "role": "agent", "open": 3, "urgent_open": 2 } ]
}
```
- 날짜는 한국 시간으로 묶습니다 (UTC로 저장된 KST 0~9시 문의가 전날로 가지 않게).
- 처리됨 = 자동 처리 + 완료, 미처리 = 접수 · 검토 대기 · 담당자 처리
- `avg_latency_ms`는 LLM이 판단한 문의만 평균 (규칙 판단은 0초라 섞으면 평균이 왜곡됨)
- 대시보드 카드에서 목록으로 이동할 수 있도록 문의 목록 API에 `open=true`(미처리만) 필터를 추가했습니다.
기획서 7장은 권한이 "필요"이지만, 6장 권한표에 맞춰 관리자만으로 정했습니다.

### GET /api/stats/activity — 최근 처리 활동 (관리자)
파라미터: `limit` (1~30, 기본 8). 최근에 움직인 문의들의 처리 이력(문의 상세의 `history`와 같은 형식)을 최신순으로 돌려줍니다.
```json
[ { "at": "2026-11-16T04:01:00+00:00", "actor": "AI", "text": "자동 답변 판단 (LLM) · FAQ 검색", "kind": "ai",
    "inquiry_id": 14, "inquiry_number": "INQ-20261116-0003", "title": "택배상자가 뜯겨 왔어요" } ]
```
- 문의 목록 API 항목에 `confidence`(AI 유형 분류 확신도 0~1)를 추가했습니다. 목록의 확신도 막대에 씁니다 (0.8 미만 = 담당자 확인).

### GET /api/admin/agent-logs — AI 실행 로그 (관리자, 상담원은 배정된 문의만)
파라미터: `inquiry_id`, `decision`, `selected_tool`, `tool_success`, `from`, `to`
- `decision`: 자동 답변 / 답변 초안 / 담당자 연결
- `selected_tool`: FAQ 검색 / 배송 조회 / 티켓 접수 / 상담원 이관 (값은 `backend/ai/prompts.py`의 `DECISIONS`, `TOOLS`와 같음)
- 성공 지표 "도구 선택 정확도"는 정답 도구를 붙인 테스트 문의(`data/test/prompt_cases.json`)를 등록한 뒤 이 로그의 `selected_tool`과 비교해 계산합니다.

### GET /api/admin/audit-logs — 작업 기록 (관리자)
파라미터: `admin_id`, `action`, `target_type`, `from`, `to`

## 8-1. 고객 FAQ API (공개, 2주차 추가)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /api/public/faqs | 활성 FAQ 목록 `[{code, category, question, answer}]` (고객 FAQ 화면 `/faq`) |
| GET | /api/public/faqs/suggest?q=&k=3 | 문의 작성 중 비슷한 FAQ 추천. 유사도가 기준값(KURE 0.6) 미만이면 빼서 관계없는 FAQ를 보여 주지 않음. 같은 IP 1분 30회 초과 시 429 |

- 추천은 에이전트와 같은 FAQ 검색(KURE-v1 + ChromaDB)을 씁니다. 기준값은 검색 방식마다 점수 범위가 달라 평가 세트로 정했습니다 (KURE 0.6, 대체용 TF-IDF 0.18, `docs/faq_search_eval.md`).
- 다른 고객의 문의는 목록으로 보여 주지 않습니다 (문의에 주문번호·개인 사정이 들어 있어 개인정보 문제).

## 9-1. 계정 관리 API (관리자, 2주차 추가)

공개 회원가입은 없습니다. 처음 계정은 `seed_admin.py`, 이후 계정은 관리자가 계정 관리 화면(`/admin/users`)에서 만듭니다.

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /api/admin/staff | 배정 선택 상자용: 활성 계정만 `[{id, username, display_name, role}]` |
| GET | /api/admin/users | 계정 목록 (비활성 포함). `is_active`, `locked_until`, `last_login_at`, `created_at` 포함, 비밀번호 해시는 내보내지 않음 |
| POST | /api/admin/users | `{ "username": "agent3", "display_name": "상담원 박서준", "role": "agent", "password": "8자 이상", "categories": ["배송", "교환"] }` → 201 |
| PATCH | /api/admin/users/{id} | 바꿀 것만: `display_name`, `role`, `is_active`, `categories` |

- `categories`(담당 유형): 8개 유형 중에서 고름. 중복은 없애고 유형 순서로 저장. 빈 목록은 "전체 담당"(맞는 담당자가 없는 유형을 받음). 자동 배정은 상담원(agent)만 받습니다.
| POST | /api/admin/users/{id}/reset-password | `{ "password": "..." }`. 실패 횟수·잠금도 풀림 |

- 아이디: 영문 소문자·숫자·밑줄 3~30자. 이미 있으면 409 `USERNAME_TAKEN`
- 비활성화·비밀번호 초기화 시 그 계정의 refresh_token을 모두 무효화합니다. access_token은 요청마다 `is_active`를 확인하므로 바로 막힙니다.
- 자기 계정을 비활성화하거나 상담원으로 바꾸면 400 `INVALID_STATE` (관리자가 없어지는 것 방지)
- 작업 기록: `user_create`, `user_update`(바뀌기 전·후 값), `user_password_reset`(비밀번호는 기록하지 않음)

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
