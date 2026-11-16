# DB 스키마 초안

기획서 v2 7장 "DB 테이블"을 바탕으로, 1주차에 정한 내용(분석 결과, 처리 방식 판단, 프롬프트 검증 결과)을 반영해 컬럼과 값을 구체화한 초안입니다.
2주차에 SQLAlchemy 모델(`backend/database/models.py`)로 옮기면서 바뀔 수 있습니다.

- DB: 개발 중에는 SQLite, 배포는 PostgreSQL (기획서 4장). 두 DB에서 모두 동작하도록 JSON은 `JSON` 타입, 날짜는 UTC `DATETIME`으로 저장합니다.
- 모든 테이블에 `id`(정수, 자동 증가)와 `created_at`이 있습니다. 표에서는 생략합니다.
- **굵게** 표시한 컬럼은 기획서 7장에 없던 것으로 이번에 추가했습니다.

## 1. 테이블 관계

```
admin_users ─┬─< inquiries (assigned_to)          관리자·상담원 ↔ 배정된 문의
             ├─< refresh_tokens                   로그아웃 시 무효화
             └─< admin_audit_logs                 누가 무엇을 했는지

customers ──< orders ──< tickets                  모의 고객·주문 (배송 조회·티켓 도구가 사용)

inquiries ─┬── analysis_results (1:1)             분류 모델 결과 + 처리 방식 판단
           ├─< responses                          답변 초안·최종 답변
           ├─< tickets                            환불·교환·취소 접수, 담당자 이관
           ├─< agent_logs                         에이전트 실행 기록
           └─< label_corrections                  관리자가 고친 분류 (재학습 데이터)

faqs                                              FAQ 원본 → ChromaDB 색인
```

## 2. 테이블

### admin_users — 관리자·상담원 계정

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| username | VARCHAR(50) UNIQUE | 로그인 아이디 |
| password_hash | VARCHAR(255) | Argon2 해시 (pwdlib). 평문은 저장하지 않음 |
| role | VARCHAR(10) | `admin` / `agent` |
| display_name | VARCHAR(50) | **화면에 보이는 이름** (배정 목록 등) |
| **categories** | JSON | **담당 유형 목록** (예: `["배송", "교환"]`). 자동 배정에 사용. 빈 목록 = 전체 담당 (2주차 추가) |
| is_active | BOOLEAN | 비활성 계정은 로그인 불가 |
| failed_login_count | INT | 연속 실패 횟수. 로그인 성공 시 0 |
| **locked_until** | DATETIME NULL | **5회 실패 시 지금+15분. 이 시각이 지나면 자동 해제** (기획서 6장) |
| last_login_at | DATETIME NULL | 마지막 로그인 |

처음 계정은 `backend/database/seed_admin.py`로, 이후 계정은 관리자가 계정 관리 화면(`/admin/users`)에서 만듭니다 (공개 회원가입 없음).

### refresh_tokens — Refresh Token 기록 (추가)

기획서 6장 "로그아웃하면 서버에 기록한 Refresh Token을 무효화"를 위한 테이블입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| user_id | FK → admin_users | |
| jti | VARCHAR(64) UNIQUE | 토큰 고유 번호 (JWT의 `jti`). 토큰 원문은 저장하지 않음 |
| expires_at | DATETIME | 만료 시각 (발급 + 7일) |
| revoked_at | DATETIME NULL | 로그아웃·재발급 시각. 값이 있으면 사용 불가 |

재발급할 때는 기존 토큰을 무효화하고 새 토큰을 발급합니다 (토큰 회전).

### inquiries — 고객 문의

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| **inquiry_number** | VARCHAR(20) UNIQUE | **고객에게 알려주는 문의 번호** (예: `INQ-20261113-0007`). 내부 `id`는 노출하지 않음 |
| customer_name | VARCHAR(50) | |
| customer_email | VARCHAR(255) | 본인 확인용 (문의 조회, 주문 확인). 소문자로 저장 |
| **lookup_password_hash** | VARCHAR(255) NULL | **문의 조회 비밀번호의 Argon2 해시.** 이메일 + 이 비밀번호로 본인 문의를 조회 (2주차 추가) |
| order_number | VARCHAR(30) NULL | 주문 관련 문의일 때만 |
| title | VARCHAR(200) | |
| content | TEXT | 문의 원문 |
| status | VARCHAR(10) | 아래 상태값 |
| assigned_to | FK → admin_users NULL | 담당 상담원 |
| **updated_at** | DATETIME | 상태가 바뀔 때마다 갱신 |

**status 값과 바뀌는 시점**

| 값 | 의미 | 들어가는 시점 |
| --- | --- | --- |
| 접수 | 등록됨, 분석 전 | 문의 등록 직후 |
| 자동 처리 | AI 자동 답변이 발송됨 | 처리 방식 = 자동 답변 + 근거 있음 |
| 검토 대기 | 답변 초안을 상담원이 검토해야 함 | 처리 방식 = 답변 초안 (자동 답변인데 근거 부족 포함) |
| 담당자 처리 | 상담원에게 이관됨 | 처리 방식 = 담당자 연결, 또는 관리자 배정 |
| 완료 | 답변 승인·발송 완료 | 상담원·관리자가 승인 |

### analysis_results — 분석 결과와 처리 방식 판단 (문의당 1개)

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| inquiry_id | FK → inquiries UNIQUE | |
| category | VARCHAR(20) | 8개 유형 (`backend/training/labels.py`) |
| confidence | FLOAT | 유형 확신도 (0~1). **0.8 미만이면 담당자 연결** |
| sentiment | VARCHAR(5) | 긍정 / 중립 / 부정 |
| **sentiment_confidence** | FLOAT | 감정 확신도. 판단 기준으로는 쓰지 않고 기록만 (확신도가 정답·오답을 잘 구분하지 못함) |
| urgency | VARCHAR(5) | 높음 / 보통 / 낮음 (`backend/ai/rules.py`) |
| route | VARCHAR(5) | 처리 경로: 조회형 / 접수형 / FAQ형 / 이관형 (유형으로 정해짐) |
| **decision** | VARCHAR(10) | **처리 방식: 자동 답변 / 답변 초안 / 담당자 연결** (기획서 2-2) |
| **decided_by** | VARCHAR(5) | **규칙 / LLM** (규칙: 확신도 낮음·긴급도 높음·기타 유형) |
| **decision_reason** | TEXT | **판단 이유** (규칙 이름 또는 LLM이 쓴 이유) |
| model_version | VARCHAR(50) | 분류 모델 버전 (예: `category_ev_s123`, `sentiment_v1`) |
| **scores** | JSON | **유형별·감정별 확률 전체** (예: `{"category": {"배송": 0.92, ...}, "sentiment": {...}}`) |

`route`(4갈래)는 유형만 보고 정해지는 기본 경로이고, `decision`(3가지)은 에이전트가 실제로 고른 처리 방식입니다.
예: "반품 배송비 얼마예요?"는 route = 접수형, decision = 자동 답변.

### responses — 답변 초안과 최종 답변

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| inquiry_id | FK → inquiries | |
| draft_text | TEXT | AI가 만든 답변 (자동 답변이면 발송된 내용과 같음) |
| final_text | TEXT NULL | 상담원이 수정·승인한 최종 답변 |
| generated_by | VARCHAR(20) | `llm` / `agent_user` (상담원이 직접 작성) |
| **used_faq_ids** | JSON | **답변 근거로 쓴 FAQ id 목록** (근거 일치 검수용) |
| **grounded** | BOOLEAN NULL | **LLM이 FAQ만으로 답할 수 있다고 판단했는지.** false면 자동 발송하지 않고 초안으로 |
| **status** | VARCHAR(10) | **초안 / 발송** |
| approved_by | FK → admin_users NULL | 자동 답변은 NULL |
| approved_at | DATETIME NULL | 발송 시각 (자동 답변은 생성 시각) |
| **is_edited** | BOOLEAN | **승인 시 draft와 final이 다른지.** 성공 지표 "답변 초안 승인율"(수정 없이 승인 70%) 계산용 |

### faqs — FAQ (벡터 DB 색인의 원본)

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| **code** | VARCHAR(10) UNIQUE | **FAQ 번호 (F01 등).** `data/faq/faqs.csv`의 id, 프롬프트·로그에 쓰는 번호 |
| category | VARCHAR(20) | 8개 유형 중 하나 |
| question | TEXT | |
| answer | TEXT | 정책 기준: `docs/shop_policy.md` |
| **is_active** | BOOLEAN | **삭제 대신 비활성 (예전 답변의 근거 FAQ를 추적하기 위해)** |
| updated_at | DATETIME | 바뀌면 ChromaDB 색인을 다시 만듦 |

처음 데이터는 `data/faq/faqs.csv`로 넣습니다.

### 고객센터 기능 테이블 (2주차 추가)

| 테이블 | 주요 컬럼 | 쓰임 |
| --- | --- | --- |
| customer_messages | inquiry_id, content | 고객 추가 문의 (같은 문의에 이어서) |
| inquiry_notes | inquiry_id, author_id, text | 상담원 내부 메모 (고객에게 안 보임) |
| attachments | token(UNIQUE), inquiry_id NULL, message_id NULL, filename, content_type, size, path | 고객 사진. 먼저 올려 token 을 받고 문의 등록 때 연결. 파일은 `data/uploads/`(Git 제외) |
| notifications | inquiry_id, channel, recipient, subject, body, status | 답변 알림 기록 (메일 서버 없이 시연용으로 기록만) |

- inquiries에 **privacy_agreed_at**(개인정보 동의 시각), responses에 **rating**(1 / -1)·**rated_at** 추가

### label_corrections — 관리자가 고친 분류 결과 (재학습 데이터)

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| inquiry_id | FK → inquiries | |
| **field** | VARCHAR(10) | **category / sentiment** |
| before_label | VARCHAR(20) | 모델 예측 |
| after_label | VARCHAR(20) | 관리자 정답 |
| **text** | TEXT | **고칠 때의 문의 원문 복사본** (재학습 CSV를 바로 만들 수 있게) |
| corrected_by | FK → admin_users | |

재학습할 때 `text, after_label`을 `docs/labeling_guide.md` 기준으로 확인한 뒤 학습 데이터에 합칩니다.

### customers — 고객 (모의 데이터)

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| name | VARCHAR(50) | |
| email | VARCHAR(255) UNIQUE | 주문 확인 시 문의 이메일과 비교 |
| phone | VARCHAR(20) | 화면에는 가운데를 가려서 표시 |

### orders — 주문·배송 (모의 데이터, 배송 조회 도구가 조회)

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| customer_id | FK → customers | |
| order_number | VARCHAR(30) UNIQUE | 예: `20261103-0042` |
| product_name | VARCHAR(200) | |
| **amount** | INT | **결제 금액 (원).** 환불 티켓·반품 배송비 안내에 사용 |
| **order_status** | VARCHAR(10) | **결제 완료 / 상품 준비 중 / 출고 / 배송 중 / 배송 완료 / 취소** (취소 가능 여부 판단: 출고 전만, `docs/shop_policy.md` 2장) |
| shipping_status | VARCHAR(20) | 배송 단계 설명 (예: "대전 HUB 도착") |
| **tracking_number** | VARCHAR(30) NULL | **송장번호** |
| ordered_at | DATETIME | |
| **delivered_at** | DATETIME NULL | **배송 완료 시각.** 반품·교환 기간(7일) 판단에 사용 |

### tickets — 환불·교환·취소 접수와 담당자 이관

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| inquiry_id | FK → inquiries | |
| order_id | FK → orders NULL | 이관 티켓은 주문이 없을 수 있음 |
| ticket_type | VARCHAR(5) | 환불 / 교환 / **취소** / 이관 (접수형 유형에 주문 취소가 있어 **취소**를 추가) |
| reason | TEXT | 고객이 쓴 사유 또는 이관 사유 (예: "긴급도 높음") |
| status | VARCHAR(5) | 접수 / 처리 중 / 승인 / 반려 |
| handled_by | FK → admin_users NULL | 처리한 상담원·관리자 |
| **handled_at** | DATETIME NULL | **승인·반려 시각** |

### agent_logs — AI 에이전트 실행 기록

성공 지표 "도구 선택 정확도", "FAQ 답변 근거 일치율"의 근거 데이터입니다. 문의 1건의 에이전트 실행 1번이 1줄입니다.

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| inquiry_id | FK → inquiries | |
| category | VARCHAR(20) | 실행 당시 유형 (analysis_results가 나중에 수정돼도 남음) |
| confidence | FLOAT | 실행 당시 유형 확신도 |
| **decision** | VARCHAR(10) | **자동 답변 / 답변 초안 / 담당자 연결** |
| **decided_by** | VARCHAR(5) | **규칙 / LLM** |
| selected_tool | VARCHAR(10) | FAQ 검색 / 배송 조회 / 티켓 접수 / 상담원 이관 |
| tool_success | BOOLEAN | 도구 실행 성공 여부 |
| **tool_output** | JSON NULL | **도구 결과 요약** (예: 배송 상태, 티켓 번호) |
| **retrieved_faqs** | JSON | **검색된 FAQ 번호와 유사도** (예: `[["F14", 0.82], ["F15", 0.41]]`) |
| **used_faq_ids** | JSON | **답변에 쓴 FAQ 번호** |
| **reason** | TEXT | **판단 이유** |
| response_text | TEXT NULL | 생성된 답변 |
| **llm_model** | VARCHAR(50) | **예: `gpt-5-mini (reasoning_effort=low)`** |
| **tokens** | JSON | **입력·출력 토큰 수** (비용 계산) |
| latency_ms | INT | 에이전트 전체 처리 시간 |
| trace_url | VARCHAR(500) NULL | LangSmith 추적 링크 |
| **error** | TEXT NULL | **실패 시 오류 내용** (LLM 응답 실패 → 초안으로 전환 등) |

### admin_audit_logs — 관리자·상담원 작업 기록

| 컬럼 | 타입 | 설명 |
| --- | --- | --- |
| admin_id | FK → admin_users NULL | 작업한 사람. 없는 아이디로 로그인 실패하면 NULL이고, 시도한 아이디는 `detail`에 남김 |
| action | VARCHAR(30) | 아래 값 |
| target_type | VARCHAR(20) | inquiry / response / ticket / faq / analysis |
| target_id | INT | |
| detail | JSON | 바뀌기 전·후 값 (예: `{"before": "검토 대기", "after": "완료"}`) |

**action 값:** login, login_failed, logout, status_change, assign, response_create, response_edit, response_approve, ticket_approve, ticket_reject, label_correct, faq_create, faq_update, faq_deactivate, user_create, user_update, user_password_reset, password_change (본인 변경), note_create, auto_assign (시스템 자동 배정, admin_id 없음)

## 3. 인덱스

| 테이블 | 인덱스 | 이유 |
| --- | --- | --- |
| inquiries | (status, created_at) | 문의 목록 필터·정렬 |
| inquiries | (assigned_to, status) | 상담원의 "배정된 문의" 목록 |
| inquiries | customer_email | 고객 문의 조회 (이메일 + 조회 비밀번호) |
| analysis_results | (urgency, category) | 긴급도 높은 순 정렬, 유형별 통계 |
| orders | order_number | 배송 조회 도구 |
| agent_logs | (inquiry_id, created_at) | 문의 상세의 실행 기록 |

## 4. 모의 데이터 (seed)

| 데이터 | 양 | 만드는 방법 |
| --- | --- | --- |
| 관리자·상담원 | 관리자 1, 상담원 2 | `seed_admin.py`. 비밀번호는 `.env`에서 읽음 |
| 고객·주문 | 고객 20명, 주문 50건 | 주문 상태를 골고루 (출고 전, 배송 중, 배송 완료 7일 이내·이후) 만들어 취소·반품 가능 여부 시연 |
| FAQ | 44개 | `data/faq/faqs.csv` |
| 시연 문의 | 최근 14일 50건 안팎 | `seed_demo.py --reset` (아래) |

### 시연 DB 만들기: `python -m backend.database.seed_demo --reset`

개발 DB를 비우고 위 계정·고객·주문·FAQ와 **최근 2주치 시연 문의**를 한 번에 넣습니다. DB 칸이 바뀌었을 때도 이 명령으로 새로 만듭니다.

- 지우기 전에 지금 DB와 첨부 사진을 `data/backups/`에 복사합니다 (GitHub에 올리지 않음).
- 문의는 앱이 저장하는 형식 그대로 만듭니다: 분석 결과, AI 실행 기록, 자동 답변·초안·상담원 답변, 자동 배정·발송 작업 기록, 알림, 티켓, 고객 평가, 추가 문의, 내부 메모. AI 모델·OpenAI는 부르지 않습니다.
- 지난주보다 이번 주 문의가 많아 대시보드의 "지난 기간 대비"가 보이고, 가장 최근 문의 몇 건은 긴급·초안 문의로 남겨 "지금 처리할 일"이 채워집니다.
- 담당 상담원이 없는 유형(기타, 쿠폰·적립금·회원)은 관리자가 맡아 처리한 것으로 만들고, 최근 것은 미배정으로 남깁니다.
- 고객 화면 "내 문의 조회": 이메일 `customer01@example.com` ~ `customer20@example.com`, 조회 비밀번호 `test1234`
- 같은 날 다시 돌려도 결과가 같도록 난수 시드를 고정했습니다 (시각은 실행한 때 기준).
- 계정은 `seed_admin.py`의 3개(admin, agent1, agent2)만 다시 만듭니다. 화면에서 따로 만든 계정은 백업 DB에만 남습니다.

## 5. 정할 것 (2주차 시작 전)

- 문의 1건에 답변이 여러 번 생길 수 있는지 (재답변). 지금은 `responses`를 1:N으로 두었습니다.
- 개인정보 보관 기간: 문의 원문과 이메일을 언제까지 보관할지 (시연 데이터라면 생략 가능)
- `label_corrections`를 재학습에 쓸 때 사람이 한 번 더 검수할지
