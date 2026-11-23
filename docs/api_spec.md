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
- 성공하면 `must_change_password`가 false가 됩니다 (아래 "임시 비밀번호").

### 임시 비밀번호 — 첫 로그인 때 비밀번호 변경 강제 (4주차 추가)
- 관리자가 계정을 만들거나(`POST /api/admin/users`) 비밀번호를 초기화하면(`reset-password`) `must_change_password=true`. 관리자가 정한 비밀번호는 관리자도 알고 있기 때문입니다.
- 이 상태로 로그인하면 `user.must_change_password: true`가 내려오고, `/api/auth/me`·`/api/auth/change-password`·`/api/auth/logout` 외 모든 로그인 API가 403 `PASSWORD_CHANGE_REQUIRED` (`core/dependencies.py`).
- 화면: 로그인 직후 "새 비밀번호 정하기"(`/change-password`)로 이동하고, 바꾸기 전에는 다른 관리 화면으로 가지 못합니다.
- `seed_admin.py`로 만든 처음 계정은 시연 편의를 위해 강제하지 않습니다.
- **비밀번호 최소 길이**는 `.env`의 `PASSWORD_MIN_LENGTH`(기본 8)를 따릅니다. 로컬 시연 환경만 4로 낮춰 `1234`를 씁니다. 배포할 때는 8 이상으로 둡니다.

### GET /api/auth/me — 내 정보 (로그인)
```json
{ "id": 2, "username": "agent1", "display_name": "김상담", "role": "agent", "must_change_password": false }
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
- **주문번호 형식:** 쇼핑몰 주문번호는 `주문일 8자리-그날 순번 4자리` (예: `20261103-0042`). 공백은 지우고, 하이픈 없는 12자리 숫자는 `8-4`로 고쳐 받습니다.
  형식이 다르면 422 (`detail[].msg`에 "주문번호는 20261103-0042처럼 숫자 8자리-4자리예요…", 화면은 이 문장을 그대로 보여 줌).
  형식은 맞지만 없는 주문은 그대로 받습니다 (고객이 잘못 적었을 수 있어 상담원이 확인, 문의 상세에 '주문번호 …를 찾을 수 없습니다').
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
| 파손 사진 | `photo_labels: {token: "송장"·"파손 부위"}`, `damage_report`, `photos_later` | 제목·내용이 파손·불량·오배송 표현이거나 `damage_report=true`면 **송장·파손 부위 사진 두 장** 필요 (아니면 422 `PHOTO_REQUIRED`, `missing`). `photos_later=true`(지금은 사진이 없어요)면 사진 없이 등록하고 `photo_request='나중에'` → 추가 문의로 사진이 오면 풀림 (`services/photo_evidence.py`) |
| 답변 평가 | `POST /api/inquiries/answers/{response_id}/rating?inquiry_number=` `{ customer_email, password, helpful }` | 본인 확인 후 `responses.rating` = 1 / -1 (다시 누르면 변경). 대시보드 "AI 자동 답변 만족도" |
| 추가 문의 | `POST /api/inquiries/follow-up` `{ customer_email, password, inquiry_number, content, attachment_tokens }` | 같은 문의에 이어서. 자동 처리·완료된 문의는 `담당자 처리`로 다시 열고, 미배정이면 자동 배정. AI 재분석은 하지 않음. 문의당 10개까지, IP 1분 5회 |
| 답변 시간 안내 | `/lookup` 응답의 `notice` | "영업일 기준 1일 이내에 답변드립니다 (평일 10:00~17:00)" |
| 답변 알림 | (자동) | 자동 답변·상담원 발송 때 "답변이 등록되었습니다" 메일 (`services/notify.py`). 본문에는 답변 내용 대신 문의 조회 링크만 |

**답변 알림 메일** (`backend/services/notify.py`, 설정은 `.env.example`)
- 기본 `MAIL_ENABLED=false`: 보내지 않고 `notifications`에 기록만 (status `기록`). 테스트·CI·화면 자동 테스트는 항상 꺼짐
- 켜면(SMTP 설정): 답변이 DB에 **커밋된 뒤** 따로 보냄 → 메일 서버가 느리거나 실패해도 답변 발송은 그대로. 저장이 취소되면(오류) 메일도 안 나감
- 결과: `발송`/`실패`(error, 예: 인증 실패)·`sent_at`. 예시 주소(example.com·.test 등)는 `건너뜀`. 다시 보내지는 않음
- `MAIL_REDIRECT_TO`(시연용): 모든 알림을 한 주소로 (제목에 원래 받는 사람). 시연 고객 주소는 가짜라서
- 문의 상세: `notifications[]`에 `error`, `sent_at`, 처리 이력에 `kind: "mail"` 줄, 화면의 보낸 답변 아래 '📧 고객 메일 발송됨/실패'
- 설정 확인: `python -m backend.services.notify --test 받을주소` (실제로 1통 보냄)

- 추가 문의·평가도 조회와 같은 잠금(같은 이메일 15분 5회 실패)을 씁니다.
- `/lookup` 응답 항목에 `answers[].id`, `answers[].rating`, `messages`(추가 문의), `attachment_count`, `attachments`, `can_follow_up`이 추가됐습니다.
- **고객이 자기 사진 보기:** 고객은 로그인 쿠키가 없어 `<img>`로 사진을 부를 때 본인 확인을 할 수 없습니다. 그래서 본인 확인(이메일 + 비밀번호)을 통과한 `/lookup` 응답에만 `attachments[].url`로 **30분짜리 서명 주소**(`GET /api/inquiries/attachments/{id}?exp=&sig=`, JWT 키로 HMAC 서명)를 넣어 줍니다. 서명이 틀리거나 시간이 지나면 404

## 3-1. 쇼핑몰 로그인 연동 API (고객, 시연용, 4주차)

실제 서비스에서는 쇼핑몰이 고객 로그인을 맡고 고객센터는 로그인한 고객 정보를 넘겨받습니다. 시연에서는 모의 고객
(`customerNN@example.com`, 비밀번호 `.env`의 `SEED_CUSTOMER_PASSWORD`)으로 그 흐름을 흉내 냅니다. 회원가입·비밀번호 찾기는 없습니다.
구현: `backend/api/shop.py`, 화면 `/shop/login`, `/my`

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | /api/shop/login | `{ "email", "password" }` → 200 `{name, email}` + 쿠키. 틀리면 401 `INVALID_CREDENTIALS` (없는 이메일도 같은 응답·같은 시간), 같은 이메일 15분 5회 실패 시 429, 같은 IP 1분 10회 |
| POST | /api/shop/logout | 204, 고객 쿠키 삭제 |
| GET | /api/shop/me | 로그인한 고객 `{name, email}` (없으면 401) |
| GET | /api/shop/orders | 내 주문 (최신순) `[{order_number, product_name, amount, order_status, shipping_status, ordered_at, delivered_at, inquiry_count}]` |
| GET | /api/shop/inquiries | 내 문의 (조회 비밀번호 없이, `/api/inquiries/lookup`과 같은 형식) |
| POST | /api/shop/inquiries/{번호}/follow-up | `{ content, attachment_tokens }` 추가 문의 (내 문의가 아니면 404) |
| POST | /api/shop/answers/{id}/rating?inquiry_number= | `{ helpful }` 답변 평가 |

- **쿠키:** `shop_session`(HttpOnly, `Path=/api`, 8시간, 종류 `shop` JWT) + `shop_csrf`(`Path=/`). 관리자 로그인 쿠키와 따로라
  한쪽 로그아웃이 다른 쪽을 끊지 않고, 고객 토큰으로 관리자 API를 쓸 수 없습니다 (토큰 종류가 다름).
- **CSRF:** 고객 로그인 상태의 POST는 `X-Shop-CSRF` 헤더에 `shop_csrf` 쿠키 값을 넣어야 합니다 (아니면 403).
- **문의 등록(`POST /api/inquiries`)과의 연결:** 고객 쿠키가 있으면 이름·이메일을 계정 정보로 채우고(화면 값 무시), 조회 비밀번호(`password`)는
  비워도 됩니다. 주문번호는 **내 주문만** (아니면 422 `ORDER_NOT_FOUND`). 비회원은 지금처럼 `password` 필수(없으면 422).
- 로그인 고객이 문의할 때 주문을 고르면 에이전트가 그 주문으로 본인 확인·배송 조회·티켓 접수를 바로 합니다.

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
  "customer_profile": { "member": true, "phone": "010-****-5678", "orders": 3, "inquiries": 4,
                        "negative_inquiries": 1, "negative_ratings": 0 },
  "faq_titles": { "F17": "반품 배송비는 얼마인가요?" },
  "history": [ { "at": "...", "actor": "AI", "text": "담당자 연결 판단 (규칙) · 상담원 이관" } ]
}
```
- `order`: 취소 가능(출고 전), 반품 기한(배송 완료 + 7일, 불량·오배송 30일)을 정책 기준으로 계산. `email_match=false`면 주문자와 문의자가 다를 수 있어 화면에 경고
- `email_orders`: 문의 이메일과 같은 이메일로 주문한 내역 최근 5건 (`order`의 주문은 제외, 각 항목은 `order`와 같은 형식). 주문번호를 적지 않은 문의도 어떤 주문인지 짐작할 수 있게 함. 문의 이메일은 본인 인증 전이라 화면에 "본인 확인 후 안내" 경고를 함께 표시하며, 관리자 화면에만 보이고 고객에게는 나가지 않음
- `customer_history`: 같은 이메일의 다른 문의 최근 5건. 상담원은 자신에게 배정된 것만
- `customer_profile`: 고객 카드 (같은 이메일 기준). `member`=쇼핑몰 회원 로그인 가능 고객, `phone`은 가운데를 가림,
  `orders`·`inquiries`=주문·문의 수, 불만 신호 `negative_ratings`(이전 답변에 👎 수)·`negative_inquiries`(부정 감정 문의 수).
  화면은 👎가 있거나 부정 문의가 2건 이상이면 "응대에 신경 쓸 고객"으로 표시
- `history`: 접수 → AI 판단 → 자동 배정·답변 발송 → 사람의 배정·상태 변경 (시간순)
- 추가 필드: `due_at`·`overdue`(답변 기한: 주말(한국 시간 토·일) 제외, 긴급 4시간, 그 외 24시간 — `backend/services/sla.py`), `messages`(고객 추가 문의), `notes`(내부 메모), `attachments`(사진 목록, token 은 내보내지 않음), `notifications`(알림 기록), `responses[].rating`

### 내부 메모·첨부 사진·기한 (2주차 추가)
| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| POST | /api/inquiries/{id}/notes | `{ "text": "택배사 확인 중" }` 상담원 내부 메모. 고객 API에는 절대 나가지 않음. audit `note_create` |
| GET | /api/inquiries/{id}/attachments/{attachment_id} | 사진 보기 (로그인, 상담원은 배정된 문의만). 저장 때 확인한 형식으로만 응답, `nosniff` |
| GET | /api/inquiries?overdue=true | 답변 기한을 넘긴 미처리만. 목록 항목에도 `due_at`, `overdue` |
| GET | /api/inquiries?recheck=true | '확인 후 다시 안내' 표시가 남은 문의만 (다시 안내 기한 가까운 순). 목록 항목에도 `recheck_note`, `recheck_due_at` |

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


**상담용 상세 (2026-11-20 추가)**
- `order` (고객이 적은 주문)와 `email_orders`의 각 주문: `quantity`, `unit_price`, `option`, `payment_method`, `paid_at`,
  `payments[]`(kind·status·method·amount·approval_no·at·memo), `duplicate_payment`, `carrier`, `shipment_events[]`(at·status·location),
  `return_requested_at`, `picked_up_at`. `order`에만 `related_inquiries[]`(같은 주문으로 들어온 다른 문의)
- `option_choices[]`: 같은 상품의 옵션별 재고 `{option, stock, sold_out, low(3개 이하), restock_at(품절일 때 재입고 예정일, 없으면 미정), current}`.
  옵션이 없는 상품은 빈 목록. 화면의 '옵션별 재고'와 [옵션 변경], AI 초안의 '같은 상품 옵션 재고' 근거 (`backend/services/inventory.py`)
- `customer_profile`: `points_balance`(적립금 잔액, 적립 예정 제외), `points_pending`, `point_history[]`(최근 5건), `coupons[]`(state: 사용 가능/사용함/만료)
- 화면: 주문 관련 유형(배송·주문 취소·교환·반품·환불·결제)인데 사람이 처리하는 문의에서 주문을 찾지 못하면 [주문번호 요청 문구 넣기] 버튼

### POST /api/inquiries/{id}/actions — 바로 처리 (로그인, CSRF, 4주차)

상담원이 문의 상세에서 조건이 맞으면 그 자리에서 끝내는 처리. 권한은 문의 상세와 같음 (관리자, 또는 배정받은 상담원).
주문 처리는 문의에 적힌 주문이고 문의 이메일 = 주문자 이메일일 때만 (아니면 409). 조건·처리는 `backend/services/order_actions.py`.

| action | 추가 값 | 조건 | 결과 |
| --- | --- | --- | --- |
| `address` | `address` | 출고 전 | 배송지 변경 |
| `option` | `option` | 출고 전, 같은 상품의 다른 옵션, 재고 ≥ 주문 수량 (아니면 409 `SOLD_OUT`) | 옵션 변경 (가격 같음), 재고 이동 (새 옵션 -수량, 원래 옵션 +수량) |
| `partial_cancel` | `count` | 출고 전, 1 ≤ count < 수량 | 수량·금액 줄임 + 결제 '승인 취소'(부분) + 열린 취소 티켓 승인 |
| `duplicate_cancel` | - | 정리되지 않은 중복 승인 (같은 금액 10분 안 두 번) | 결제 '승인 취소' 1건 |
| `points` | `amount`, `reason` | 쇼핑몰 고객, 상담원 3,000원 / 관리자 50,000원까지 (넘으면 403) | 적립금 +amount |
| `coupon` | `coupon` | 쇼핑몰 고객. '사과 쿠폰 5,000원'은 관리자만 | 쿠폰 발급 (30일) |
| `return` | `reason`(단순 변심 / 불량·오배송) | 배송 완료, 기한 안 (7일 / 30일), 아직 접수 전 | 반품 접수 (회수 1~3영업일) |

응답 `{ok, message}`. 처리는 작업 기록(`order_action`, 바뀌기 전·후)에 남고, 문의의 처리 이력·대화 안내 줄과
[AI 초안 다시 만들기]의 처리 기록("상담원 처리 완료: …")에 들어갑니다.

### GET /api/inquiries/{id}/queue — 처리 대기열의 이전·다음 문의 (로그인, 4주차)
```json
{ "total": 12, "position": 3, "prev_id": 41, "next_id": 52 }
```
- 대기열 = 미처리(접수·검토 대기·담당자 처리), **긴급도 높은 순 → 오래된 순**. 상담원은 배정된 문의만.
- 지금 문의가 대기열에 없으면(완료 등) `position: null`, `next_id` = 대기열의 첫 문의 → 상세 화면의 [◀][▶]와 "다음 미처리 문의 →" 버튼.

## 5. 답변 API (로그인, 2주차 구현)

권한은 문의와 같습니다 (관리자 전체, 상담원은 배정된 문의만). 구현: `backend/api/responses.py`

### POST /api/inquiries/{id}/responses — 상담원 직접 작성 (추가)
```json
{ "text": "고객님, 답변이 늦어져 죄송합니다. ...", "send": true }   // send=false 면 초안으로 저장
```
- `generated_by = agent_user`. 보내지 않은 초안이 이미 있으면 409 `DRAFT_EXISTS` (`response_id` 함께 반환, 그 초안을 수정)
- 발송 후에도 추가 답변을 새로 작성할 수 있습니다 (문의 1건에 답변 여러 개). audit_logs (response_create)

### 확인 후 다시 안내 (4주차)
바로 답할 수 없어 "확인 후 다시 안내드리겠습니다"를 먼저 보낼 때, 잊지 않게 문의에 **확인할 내용·다시 안내할 기한**을 남깁니다.
구현: `backend/services/recheck.py`

- 발송할 때 함께: `POST /api/inquiries/{id}/responses`(send=true) · `POST /api/responses/{id}/approve` 본문에
  `"recheck": {"note": "택배사 분실 조사 결과", "due_at": "2026-11-22T01:00:00Z"}` (note 1~200자, 기한은 지금 이후 14일 안, 아니면 422)
- `recheck` 없이 발송하면 이번 답변이 다시 안내한 것이므로 표시가 자동으로 풀립니다 (다시 체크하면 새 내용·기한으로 바뀜)
- 문의 상태는 그대로 `완료` (첫 답변은 보냈으므로 답변 기한 초과로 보지 않음)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| PUT | /api/inquiries/{id}/recheck | `{note, due_at}` 표시 정하기·바꾸기 (발송 없이) |
| DELETE | /api/inquiries/{id}/recheck | 답변 없이 표시 풀기 (전화 등 다른 방법으로 안내했을 때). 표시가 없으면 409 `NO_RECHECK` |

- 권한은 문의와 같음. 작업 기록 `recheck_set`(before·after) / `recheck_clear`(reason: answered·manual), 문의의 처리 이력·대화 안내 줄
- 문의 상세 `recheck: {note, due_at, set_at, set_by, overdue}` (없으면 null)
- 보이는 곳: 목록 `?recheck=true`, 대시보드 `GET /api/stats/priorities`의 `rechecks`, 🔔 알림 `recheck`(기한 1시간 전부터)
- 고객 조회에는 `more_answer_coming: true`만 보냄 → 고객 화면 상태 '추가 안내 예정' (확인할 내용은 내부 정보라 보내지 않음)
- [AI 초안 만들기]의 처리 기록에 "다시 안내하기로 한 내용"이 들어가 확인 결과 안내 초안을 쓰기 쉬움

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
{ "replace": false, "instruction": "더 짧게" }   // 본문 생략 가능, instruction은 선택 (200자)
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
- `instruction`: 상담원 요청 ("더 짧게", "사과를 먼저" 등). LLM 입력 끝에 `[상담원 요청]`으로 붙고, 정책·근거 규칙 안에서만
  따릅니다 (약속 문구 금지 규칙은 그대로). 고객 글이 아니라 상담원 지시로 다룹니다. 이력에 "(요청: …)"으로 보입니다.
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

### PATCH /api/tickets/{id} — 승인·반려 (로그인, 4주차 구현: `backend/api/tickets.py`)
```json
{ "status": "승인", "memo": "택 제거 전 상태 확인" }   // 200: 티켓 (status, memo, handled_by, handled_at)
```
- 권한: 관리자, 또는 그 문의를 배정받은 상담원 (아니면 403). 취소·교환·환불 티켓만 (이관 티켓은 422), 이미 처리된 티켓은 409 `TICKET_DONE`.
- **취소 승인**은 출고 전 주문(결제 완료·상품 준비 중)만 → 주문 상태를 '취소'로 바꿈. 이미 출고된 주문은 409 (반려 후 반품 안내).
- 교환·환불 승인은 티켓만 승인 (회수·환불은 실제 쇼핑몰 시스템의 일, 시연에서는 기록만). **반려는 `memo`(사유) 필수** (422).
- audit_logs `ticket_approve` / `ticket_reject` (target: 문의, detail: ticket_id·ticket_type·memo·주문 상태 전→후) → 문의 처리 이력에 "티켓 #8 취소 승인 · 주문 결제 완료 → 취소".
- [AI 초안 다시 만들기]의 근거(처리 기록)에 티켓 상태·메모가 들어가 결과를 반영한 답변 초안을 씁니다.
- 화면: 문의 상세 오른쪽 "접수된 티켓" (처리할 티켓이 있으면 맨 위), [취소 승인] / [반려 + 사유].

## 7. 주문 API

### GET /api/orders/{order_number}/shipping?email= — 배송 조회 (내부: 에이전트 도구)
```json
{ "order_number": "20261103-0042", "product_name": "경량 패딩", "order_status": "배송 중",
  "shipping_status": "대전 HUB 도착", "tracking_number": "6012-3456-7890", "ordered_at": "..." }
```
- `email`이 주문 고객 이메일과 다르면 404 (다른 고객 정보 노출 방지, 기획서 10장 완료 기준)
- 경로 변수는 기획서의 `{order_id}` 대신 고객이 아는 `order_number`를 씁니다.

## 8. FAQ API (관리자)

관리자만 (상담원 403). 구현: `backend/api/faqs_admin.py`, 화면 `/admin/faqs` (4주차)

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /api/faqs | 목록 (활성 먼저, 번호순). `category`, `q`(번호·질문·답변), `include_inactive`(기본 true). 항목마다 `used_count`·`last_used_at` (AI 자동 답변·초안의 근거로 쓰인 횟수, `agent_logs.used_faq_ids`) |
| POST | /api/faqs | `{ "category": "배송", "question": "...", "answer": "...", "code": "F45" }` → 201. `code`를 비우면 다음 번호. 번호가 이미 있으면 409 `FAQ_CODE_TAKEN` |
| PUT | /api/faqs/{id} | `{ category, question, answer, is_active }` 전체 수정. `is_active: true`로 다시 활성화 |
| DELETE | /api/faqs/{id} | 실제로 지우지 않고 `is_active=false` (지난 답변의 근거 FAQ 번호가 남아 있어서) |
| GET | /api/faqs/search-test?q=&k=3 | 검색 미리 보기: 이 질문이면 어떤 FAQ가 검색되는지 `{engine, suggest_min_score, hits:[{code, category, question, score, suggested}]}` |
| POST | /api/faqs/suggestions | **FAQ 자동 추천** `{ "days": 30, "min_count": 2 }` → `{candidates, engine, items:[{count, category, question, answer, check_points, drafted, with_staff_answer, nearest_faq, examples}]}` (같은 IP 1분 5회) |

- 입력 제한: 유형은 8개 중 하나, 질문 5~200자, 답변 10~1,000자 (422).
- 등록·수정·비활성 뒤 **검색 색인(KURE + ChromaDB)을 바로 다시 만들어** 에이전트·고객 추천·FAQ 화면에 반영합니다 (`services/faqs.py` `refresh_search`, 바뀐 FAQ 벡터만 다시 계산). 실패하면 기존 색인을 유지하고 서버 로그에 남깁니다.
- 작업 기록: `faq_create`, `faq_update`(바뀐 칸만 before·after), `faq_deactivate`. 바뀐 것이 없으면 기록하지 않습니다.
- 답변을 바꿀 때는 `docs/shop_policy.md`와 맞는지 확인합니다. 이미 보낸 답변은 바뀌지 않습니다.
- **FAQ 자동 추천** (`services/faq_suggest.py`, 4주차): 최근 N일 문의 중 AI가 자동 답변하지 못했고(초안·담당자 연결) 긴급도 높음(항의)이 아니며
  **지금 FAQ 중 비슷한 것이 없는**(검색 1위 유사도 < 고객 추천 기준값) 문의를 FAQ 검색과 같은 방식(KURE, 없으면 TF-IDF)으로 묶습니다
  (같은 묶음 기준 KURE 0.7 / TF-IDF 0.25). 2건 이상인 묶음마다 LLM이 질문·답변 초안을 쓰는데, 근거는 **상담원이 실제로 보낸 답변**만 쓰고
  확인이 필요한 곳은 `[확인 필요: …]`로 남깁니다. 자동으로 등록하지 않고, 화면에서 [등록 폼 채우기] → 관리자가 고쳐서 등록합니다
  (`[확인 필요` 가 남아 있으면 등록 버튼이 잠김). FAQ를 등록하면 그 묶음은 다음 추천에서 빠집니다. LLM이 없으면 묶음만 돌려줍니다.

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

### GET /api/stats/priorities — 지금 가장 급한 문의 + 기한 임박 문의 (관리자, 4주차)

대시보드 '지금 처리할 일' 아래 두 카드. 쿼리: `limit` (1~20, 기본 5)

- `next`: 처리 대기열의 첫 문의 (긴급도 높은 순 → 오래된 순, 문의 상세의 이전·다음과 같은 순서). 미처리가 없으면 null
- `due_soon`: 아직 답변 기한이 남은 미처리 문의를 기한이 가까운 순으로 (기한을 넘긴 문의는 '답변 기한 초과'에서 봄)
- 항목: `id, inquiry_number, title, customer_name, preview(내용 앞 90자), status, category, urgency, assigned_to(이름), created_at, due_at, overdue`
- 답변 기한은 계산값(주말 제외, 긴급 4시간, 그 외 24시간)이라 DB에서 정렬할 수 없어, 미처리 문의를 읽어 파이썬에서 정렬합니다 (미처리는 많지 않음).
  목록의 `?overdue=true`도 같은 이유로 미처리 문의의 기한을 계산해 거릅니다
- `rechecks`: '확인 후 다시 안내' 표시가 남은 문의 (다시 안내 기한 가까운 순, 위 항목 + `recheck_note, recheck_due_at, recheck_overdue`), `recheck_total`: 전체 수

```json
{"open": 6, "next": {"id": 48, "title": "상품이 파손되어 왔어요", "urgency": "높음", "overdue": true, "...": "..."}, "due_soon": []}
```

### GET /api/stats/products — 상품별 문의 (관리자, 4주차)
파라미터: `from`, `to` (KST, 기본 최근 30일, 최대 92일), `limit` (1~20, 기본 5). 대시보드 "문의가 많은 상품" 패널.
```json
{ "range": {...}, "total": 64, "linked": 18, "products": 14,
  "items": [ { "product": "와이드 데님 팬츠", "count": 3, "by_category": { "교환": 2, "상품": 1 }, "top_category": "교환",
               "negative": 1, "auto": 1, "hint": "교환이 많아요 → 사이즈표·색상 실물 사진 보강",
               "examples": [ { "inquiry_id": 12, "inquiry_number": "INQ-…", "title": "…", "category": "교환" } ] } ] }
```
- 실제 주문에 연결된 문의만 셉니다 (`linked`). 상품 이름 끝의 옵션 괄호는 떼고 묶습니다 ("와이드 데님 팬츠 (연청, 28)" → "와이드 데님 팬츠").
- `hint`: 가장 많은 유형에 맞춘 상세페이지 개선 힌트 (채널톡 '주문 연동 상담' 벤치마킹: 같은 상품에 단순 문의가 몰리면 상세페이지가 충분히 설명하지 못한다는 신호).

### GET /api/stats/drafts — AI 초안 수정 분석 (관리자, 4주차)
파라미터: `from`, `to` (KST, **보낸 날짜** 기준, 기본 최근 30일, 최대 92일), `examples` (0~20, 기본 5). 화면: /admin/drafts.
대상은 상담원이 승인해 보낸 AI 초안입니다 (`generated_by="llm"`, `status="발송"`, `approved_by` 있음). 자동 발송과 상담원이 처음부터 쓴 답변은 비교할 초안이 없어 뺍니다.
```json
{ "range": {...},
  "summary": { "count": 11, "unedited": 8, "unedited_rate": 0.7273, "avg_change": 0.1266, "target": 0.7,
               "levels": { "그대로": 8, "조금 고침": 1, "많이 고침": 2 }, "kinds": { "덧붙임": 1, "줄임": 0, "고쳐 씀": 2 },
               "ai_share": 0.8382, "median_wait_min": 628.7, "waiting": 3 },
  "by_category": [ { "category": "교환", "count": 4, "unedited": 3, "unedited_rate": 0.75, "avg_change": 0.0885 } ],
  "by_staff": [ { "id": 2, "display_name": "상담원1", "count": 11, ... } ],
  "daily": [ { "date": "2026-11-18", "count": 2, "unedited": 1 } ],
  "regenerate": { "count": 2, "with_instruction": 2, "top_instructions": [ { "text": "더 짧게", "count": 1 } ] },
  "examples": [ { "inquiry_id": 12, "inquiry_number": "INQ-…", "title": "…", "category": "상품", "staff": "상담원1",
                  "level": "많이 고침", "kind": "고쳐 씀", "change": 0.6488, "added": 80, "removed": 53, "sent_at": "…",
                  "segments": [ { "op": "same", "text": "상품 페이지 " }, { "op": "del", "text": "…" }, { "op": "add", "text": "…" } ] } ] }
```
- `change` (바뀐 정도) = 1 − 글자 단위 유사도 (difflib). `level`: 그대로(0) / 조금 고침(0.2 미만) / 많이 고침.
- `kind`: 덧붙임(지운 것 없이 더함) / 줄임(더한 것 없이 지움) / 고쳐 씀.
- `ai_share`: 보낸 답변 글자 중 AI 초안에서 그대로 온 글자의 비율.
- `median_wait_min`: 초안이 만들어진 뒤 보낼 때까지 걸린 시간의 중앙값(분). `waiting`: 지금 검토를 기다리는 초안 수.
- `regenerate`: [AI 초안 만들기]를 다시 누른 기록(감사 로그 `draft_generate`)과 자주 적은 요청.
- `examples`: 많이 고친 순. `segments`는 띄어쓰기 단위 비교입니다 (`same`/`del`/`add`).
- `unedited_rate`는 대시보드의 `approval_without_edit_rate`와 같은 기준입니다 (성공 지표 70% 이상).

### GET /api/notifications — 내 알림 (로그인, 4주차)

오른쪽 위 🔔. 알림을 따로 저장하지 않고 이미 있는 기록에서 '나에게 해당하는 새 일'을 골라 만듭니다 (최근 7일, 최신순 20건).

| kind | 무엇 | 상담원 | 관리자 |
| --- | --- | --- | --- |
| `assigned` | 문의가 나에게 배정됨 (자동·수동, 내가 한 배정은 제외) | 나에게 배정 | 나에게 배정 + 미배정 긴급 문의 접수 |
| `followup` | 고객 추가 문의 | 내 담당 문의 | 내 담당 + 미배정 문의 |
| `due_soon` | 답변 기한 1시간 이내 (미처리, 알림 시각 = 기한 1시간 전) | 내 담당 문의 | 내 담당 + 미배정 문의 |
| `bad_rating` | 고객 👎 '도움 안 됨' | 내가 보낸 답변 | 모든 답변 (AI 자동 답변 포함) |
| `recheck` | '확인 후 다시 안내' 기한 1시간 전부터 (지나도 풀 때까지, 알림 시각 = 기한 1시간 전) | 내 담당 문의 | 내 담당 + 미배정 문의 |

```json
{"unread": 1, "items": [{"kind": "followup", "at": "…", "inquiry_id": 48, "inquiry_number": "INQ-…", "title": "…", "text": "오하린 고객의 추가 문의", "unread": true}]}
```

### POST /api/notifications/seen — 알림을 모두 읽음으로 (로그인, CSRF)

계정의 `notifications_seen_at`을 지금으로 바꿈. 이후 알림만 `unread`. 화면은 30초마다 목록을 다시 불러옵니다.

### 답변 문구 — /api/reply-templates (4주차)

상담원이 답변 칸의 [문구·주문 정보 넣기]로 넣는 자주 쓰는 문장. 관리자가 '답변 문구' 화면(`/admin/templates`)에서 편집합니다.
서버가 켜질 때 표가 비어 있으면 기본 문구 8개(`backend/services/reply_templates.py`)를 넣습니다.

| 메서드 · 경로 | 권한 | 설명 |
| --- | --- | --- |
| `GET /api/reply-templates` | 로그인 | 사용 중인 문구 (순서대로). 관리자는 `?all=true`로 숨긴 문구까지 |
| `POST /api/reply-templates` | 관리자 | `{label(1~20자), text(2~500자)}` 추가 → 맨 뒤 |
| `PATCH /api/reply-templates/{id}` | 관리자 | `label`·`text`·`is_active`(숨김) 변경 |
| `DELETE /api/reply-templates/{id}` | 관리자 | 삭제 (204) |
| `PUT /api/reply-templates/order` | 관리자 | `{ids: [...]}` 모든 문구 id 를 원하는 순서로 (일부만 보내면 422) |

모든 변경은 작업 기록(`template_create`·`template_update`·`template_delete`·`template_reorder`)에 남습니다.

### GET /api/audit-logs — 작업 기록 (관리자, 4주차)

누가 · 언제 · 무엇을 했는지 (읽기 전용). 쿼리: `group`(로그인·보안 / 계정 / 문의 처리 / 답변 / 설정),
`actor`(계정 id, `system` = 자동 배정 등, `unknown` = 없는 아이디로 로그인 시도), `days`(1~90, 기본 7), `page`, `size`(기본 30)

```json
{"total": 120, "login_failed": 2, "items": [{"at": "…", "action": "login_failed", "label": "로그인 실패", "group": "로그인·보안",
  "actor": {"id": null, "name": "알 수 없음"}, "target": null, "summary": "없는 아이디 · 시도한 아이디 'nobody'", "ip": "127.0.0.1"}]}
```

- `summary`: 사람이 읽는 한 줄 (배정 "상담원 A → 상담원 B", 상태 "검토 대기 → 완료", 티켓 "취소 · 주문 … 결제 완료 → 취소" 등)
- `target`: 문의(문의 번호, 상세 링크) · 계정 · FAQ 코드 · 답변 문구 이름. 지운 문구는 기록에 남긴 이름으로
- 비밀번호·토큰은 처음부터 기록하지 않습니다 (`services/audit.py`)

### GET /api/stats/activity — 최근 처리 활동 (관리자)
파라미터: `limit` (1~30, 기본 8). 최근에 움직인 문의들의 처리 이력(문의 상세의 `history`와 같은 형식)을 최신순으로 돌려줍니다.
```json
[ { "at": "2026-11-16T04:01:00+00:00", "actor": "AI", "text": "자동 답변 판단 (LLM) · FAQ 검색", "kind": "ai",
    "inquiry_id": 14, "inquiry_number": "INQ-20261116-0003", "title": "택배상자가 뜯겨 왔어요" } ]
```
- 문의 목록 API 항목에 `confidence`(AI 유형 분류 확신도 0~1)를 추가했습니다. 목록의 확신도 막대에 씁니다 (0.8 미만 = 담당자 확인).

### GET /api/admin/agent-logs — AI 실행 로그 (관리자, 상담원은 배정된 문의만)
구현: `backend/api/agent_logs.py`, 화면 `/admin/agent-logs` (4주차)

파라미터: `inquiry_id`, `decision`, `decided_by`(규칙 / LLM), `selected_tool`, `tool_success`, `problem`(true: 오류·도구 실패·확신도 0.8 미만만), `from`, `to` (KST 날짜, 최대 92일), `page`, `size`(1~100, 기본 30)
- `decision`: 자동 답변 / 답변 초안 / 담당자 연결
- `selected_tool`: FAQ 검색 / 배송 조회 / 티켓 접수 / 상담원 이관 (값은 `backend/ai/prompts.py`의 `DECISIONS`, `TOOLS`와 같음)
```json
{ "total": 51, "page": 1, "size": 30,
  "summary": { "count": 51, "by_decision": { "자동 답변": 22, "답변 초안": 8, "담당자 연결": 21 },
               "by_decided_by": { "LLM": 39, "규칙": 12 },
               "by_tool": { "FAQ 검색": { "count": 27, "failed": 0 }, "배송 조회": { "count": 2, "failed": 2 } },
               "errors": 0, "tool_failures": 2, "low_confidence": 1,
               "avg_latency_ms": 4100, "max_latency_ms": 8500,      // LLM이 판단한 실행만 (규칙 판단은 0초)
               "tokens": { "input": 52000, "output": 21000, "calls": 80 } },
  "items": [ { "id": 51, "created_at": "...", "inquiry_id": 51, "inquiry_number": "INQ-20261117-0004",
               "inquiry_title": "...", "inquiry_status": "자동 처리", "category": "배송", "confidence": 0.97,
               "decision": "자동 답변", "decided_by": "LLM", "selected_tool": "FAQ 검색", "tool_success": true,
               "retrieved_faqs": [["F21", 0.74]], "used_faq_ids": ["F21"], "steps": ["FAQ 검색", "규칙 판단", "LLM 판단"],
               "reason": "...", "response_text": "...", "llm_model": "...", "tokens": {...}, "latency_ms": 3900,
               "trace_url": "https://smith.langchain.com/...", "tool_output": {...}, "error": null } ],
  "faq_titles": { "F21": "해외로도 배송되나요?" } }
```
- `summary`는 필터에 맞는 **전체** 실행의 합계입니다 (현재 페이지만이 아님). 최신순 정렬.
- 성공 지표 "도구 선택 정확도"는 정답 도구를 붙인 테스트 문의(`data/test/prompt_cases.json`)를 등록한 뒤 이 로그의 `selected_tool`과 비교해 계산합니다.

### GET /api/admin/retraining — 재학습 현황 (관리자, 4주차)
구현: `backend/api/retraining.py`, 화면 `/admin/retraining`
- `model`: 지금 쓰는 모델 (`evaluation/model_history.json`의 current 항목 + `category_model_version`)
- `corrections`: `{total, by_field: {유형, 감정}, pending}` — `pending`은 지금 모델 학습(`trained_at`) 뒤에 쌓인 수정 = 다음 재학습 대상
- `patterns`: 자주 고친 패턴 `[{field, before, after, count, pending, examples[{inquiry_id, text}]}]` (많은 순) — 모델의 약점
- `recent`: 최근 수정 20건, `history`: 모델 버전별 학습 데이터·점수(외부·직접 쓴 평가용·실전)·메모
- 재학습 실행은 GPU가 필요해 API로 열지 않고 명령으로 합니다 (`docs/retraining.md`). 모델을 바꾸면 `model_history.json`에 한 줄 더하고 `current`를 옮깁니다.

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
- 만들기·비밀번호 초기화로 정한 비밀번호는 **임시 비밀번호**입니다: 다음 로그인 때 본인이 바꿔야 다른 API를 쓸 수 있습니다 (위 "임시 비밀번호", 목록의 `must_change_password`).

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
