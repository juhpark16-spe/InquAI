---
version: 1.0
name: InquAI-design-system
description: InquAI(쇼핑몰 고객 문의 자동 분석·처리 AI 에이전트) 디자인 시스템. 페리윙클 톤 그라데이션 바탕, 부드러운 라운딩, 세 개의 둥근 판 레이아웃, 관리 도구용 5단계 타이포그래피(Pretendard), 파란색(#4b5bd6) 기본 액션을 기반으로 설계되었습니다.

colors:
  primary: "#4b5bd6"
  primary-hover: "#3e4cc0"
  primary-soft: "#e6e9fb"
  primary-disabled: "#e5e5e5"
  ink: "#0f172a"
  body: "#334155"
  body-strong: "#1e293b"
  muted: "#64748b"
  muted-soft: "#94a3b8"
  hairline: "#e0e5f3"
  hairline-soft: "#f1f5f9"
  canvas: "#dde4f6"
  surface-soft: "#eef1fb"
  surface-card: "#ffffff"
  surface-strong: "#dfe4f5"
  on-primary: "#ffffff"
  brand-pink: "#ff4d8b"
  brand-teal: "#1a3a3a"
  brand-lavender: "#b8a4ed"
  brand-peach: "#ffb084"
  brand-ochre: "#e8b94a"
  brand-mint: "#a4d4c5"
  brand-coral: "#ff6b5a"
  success: "#22c55e"
  warning: "#f59e0b"
  error: "#ef4444"

typography:
  page-title:
    fontFamily: "Pretendard Variable, Pretendard, Inter, sans-serif"
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.35
  text-lg:
    fontFamily: "Pretendard Variable, Pretendard, Inter, sans-serif"
    fontSize: 17px
    fontWeight: 600
    lineHeight: 1.5
  text-base:
    fontFamily: "Pretendard Variable, Pretendard, Inter, sans-serif"
    fontSize: 15px
    fontWeight: 400
    lineHeight: 1.6
  text-sm:
    fontFamily: "Pretendard Variable, Pretendard, Inter, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.375
  text-xs:
    fontFamily: "Pretendard Variable, Pretendard, Inter, sans-serif"
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.25
  display:
    fontFamily: "Pretendard Variable, Pretendard, Inter, sans-serif"
    fontWeight: 500
    letterSpacing: -0.03em
  button:
    fontFamily: "Pretendard Variable, Pretendard, Inter, sans-serif"
    fontSize: 14px
    fontWeight: 600
    lineHeight: 1
  nav-link:
    fontFamily: "Pretendard Variable, Pretendard, Inter, sans-serif"
    fontSize: 14px
    fontWeight: 500
    lineHeight: 1.4

rounded:
  xs: 6px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 20px
  2xl: 24px
  3xl: 28px
  pill: 9999px
  full: 9999px

spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px 18px
    height: 40px
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "{colors.on-primary}"
  button-primary-disabled:
    backgroundColor: "{colors.primary-disabled}"
    textColor: "{colors.muted}"
    rounded: "{rounded.md}"
  button-secondary:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 10px 18px
    height: 40px
    border: "1px solid {colors.hairline}"
  button-text-link:
    backgroundColor: transparent
    textColor: "{colors.primary}"
    typography: "{typography.text-sm}"
  text-input:
    backgroundColor: "{colors.surface-card}"
    textColor: "{colors.ink}"
    typography: "{typography.text-base}"
    rounded: "{rounded.md}"
    padding: 10px 14px
    height: 42px
    border: "1px solid {colors.hairline}"
  text-input-focused:
    backgroundColor: "{colors.surface-card}"
    borderColor: "{colors.primary}"
    ring: "2px {colors.primary-soft}"
  card:
    backgroundColor: "{colors.surface-card}"
    rounded: "{rounded.lg}"
    padding: 20px
    border: "1px solid {colors.hairline}"
  badge-pill:
    typography: "{typography.text-xs}"
    rounded: "{rounded.pill}"
    padding: 2px 10px
---

## Overview

InquAI의 프론트엔드는 장시간 화면을 주시하는 관리자 및 상담원이 눈의 피로 없이 집중할 수 있도록 정돈된 대시보드 UI를 제공합니다.
화면 구성은 **푸른 페리윙클 톤 그라데이션 바탕** 위에 **떠 있는 세 개의 둥근 판(사이드바, 헤더, 본문)**을 배치하고, 가독성을 극대화한 **5단계 타이포그래피**와 친근한 둥근 모서리 체계를 사용합니다.

### 핵심 디자인 특징
- **바탕 분위기**: 상단 `#e6eaf9`에서 하단 `#d2dbf3`로 흐르는 고정 그라데이션 바탕 (`--color-canvas: #dde4f6`).
- **주요 액션(CTA)**: 신뢰감을 주는 블루 계열 (`--color-primary: #4b5bd6`, hover `#3e4cc0`).
- **틀 구조**: 화면 위에 떠 있는 세 개의 둥근 판(사이드바, 상단 검색/사용자 바, 본문 영역)과 내부의 깨끗한 흰색 카드.
- **가독성 중심 타이포그래피**: Pretendard 글꼴 기반의 직관적인 5단계 크기 체계 (최소 13px ~ 제목 24px).
- **정보 노출 원칙**: 현재 화면 작업에 필요한 핵심 정보만 노출 (AI 실행 상세·토큰 등은 관리자 전용 영역으로 분리).

---

## Colors

### Brand & Primary
- **Primary** (`#4b5bd6`): 기본 버튼, 활성화된 메뉴/탭, 링크, 주요 상태 표시.
- **Primary Hover** (`#3e4cc0`): 버튼 호버 상태.
- **Primary Soft** (`#e6e9fb`): 활성 메뉴 배경, 선택 상태 강조 배경.
- **Brand Point**: `brand-pink` (#ff4d8b), `brand-lavender` (#b8a4ed), `brand-teal` (#1a3a3a) 등 문의 챗봇 말풍선 및 포인트 요소에 활용.

### Surface & Background
- **Canvas** (`#dde4f6`): 페이지 기본 바탕 (그라데이션: `#e6eaf9` 0% → `#dde4f6` 50% → `#d2dbf3` 100%).
- **Floating Panels**: 반투명 흰색 (`white/45~55` + backdrop-blur)으로 바탕과 분리된 떠 있는 판 구성.
- **Surface Card** (`#ffffff`): 콘텐츠가 담기는 실제 카드 표면 (흰색).
- **Hairline** (`#e0e5f3`): 카드 및 인풋 테두리 (1px).

### Text
- **Ink** (`#0f172a`): 제목 및 중요 수치 (Tailwind slate-900).
- **Body** (`#334155`): 일반 본문 텍스트 (Tailwind slate-700).
- **Muted** (`#64748b`): 보조 설명, 라벨, 비활성 텍스트 (Tailwind slate-500).

### Semantic (색상의 의미)
- **빨강** (`#ef4444`): 긴급도 '높음', 답변 기한 초과, 부정 감정, 불만(👎).
- **초록** (`#22c55e`): 정상, 완료 가능, 만족(👍), 긍정.
- **파랑** (`#4b5bd6`): 접수, 검토 대기, 담당자 처리 중, 기본 액션.
- **회색** (`#64748b`): 처리 완료, 자동 처리, 약한 상태값(보통·낮음·중립은 배지 없이 텍스트만 표시).

---

## Typography

화면 전체에 **Pretendard Variable** 글꼴을 적용하며, 복잡한 업무 화면에 최적화된 5단계 글씨 크기를 준수합니다.

| 단계 | 크기 | 행간 | 용도 |
|---|---|---|---|
| `page-title` (`text-2xl`) | 24px | 1.35 | 모든 페이지 제목 (font-bold) |
| `text-lg` | 17px | 1.5 | 구역 및 카드 제목 (font-semibold) |
| `text-base` | 15px | 1.6 | 본문 (문의 내용, 답변 작성, 핵심 데이터 값) |
| `text-sm` | 14px | 1.375 | 표 내용, 보조 설명, 버튼 레이블 |
| `text-xs` | 13px | 1.25 | 날짜·시각, 건수, 배지 라벨 (최소 글씨 크기) |

*예외: 대시보드 통계 카드 지표 숫자(30~36px) 및 로그인 화면 로고 서비스명만 예외적으로 크게 적용.*

---

## Layout & Panels

### 세 개의 둥근 판 레이아웃
1. **사이드바 (Sidebar)**:
   - 좌측에 떠 있는 반투명 판 (`white/45` + backdrop-blur), 화면 가장자리에서 16px 여백.
   - 모서리 `rounded-3xl` (모바일 `rounded-2xl`).
   - 현재 선택 메뉴: 흰 바탕 + 좌측 파란색 액센트 막대.
2. **상단 판 (Top Bar)**:
   - 검색창('/' 단축키로 포커스) + 알림 벨 + 로그인 사용자 정보/로그아웃.
   - 스크롤 시 화면 상단에 고정 (`--admin-header-bottom: 5.75rem` / lg `6.25rem`).
   - 스크롤 시 배경이 비치지 않도록 상하 여백 띠를 배경 그라데이션으로 마스킹.
3. **본문 판 (Content Panel)**:
   - 콘텐츠가 담기는 판 (`white/35`), 내부에 순백색 카드(`bg-white`) 배치.

### 문의 상세 화면 (2열 배치)
- **좌측 영역 (넓은 폭)**: '문의 내용 및 답변 작성'(주요 업무 영역).
- **우측 정보 패널 (고정 폭 22~25rem)**:
  - 상담 판단(취소 가능·반품 기한·배송 상태)의 핵심인 주문 정보를 최상단에 배치.
  - 배치 순서: 상담원 공유 메모 → 처리할 티켓 → **주문 정보** → 고객 정보 → AI 분석 요약 → 연결된 티켓 → AI 처리 상세(관리자).
  - 우측 정보 패널의 폰트는 본문(15px)보다 한 단계 작은 14px(값) / 13px(라벨) 적용.

---

## Shapes & Radius

부드럽고 둥근 모서리로 모던하고 친근한 인상을 전달합니다.

- `{rounded.sm}` (8px): 작은 태그, 내부 서브 요소.
- `{rounded.md}` (12px): 버튼, 입력창(Input).
- `{rounded.lg}` (16px): 콘텐츠 카드, 모달 다이얼로그.
- `{rounded.2xl}` ~ `{rounded.3xl}` (24~28px): 사이드바, 헤더, 본문 컨테이너 판.
- `{rounded.pill}` (9999px): 상태 배지, 카테고리 탭, 아바타.

---

## Components

### Buttons
- **`button-primary`**: 파란색 바탕 (`#4b5bd6`), 흰색 글씨, 높이 40px, 모서리 12px.
- **`button-secondary`**: 흰색 바탕, 1px 테두리(`hairline`), 잉크색 글씨.
- **`button-text-link`**: 배경 없이 파란색 글씨로 작동하는 텍스트 링크 버튼.

### Forms & Inputs
- **`text-input`**: 흰색 바탕, 높이 42px, 1px 테두리(`hairline`), 모서리 12px.
- **`text-input-focused`**: 테두리가 파란색(`primary`)으로 강조되며 소프트 링 효과 적용.

### Cards & Badges
- **`card`**: 흰색 바탕 (`bg-white`), 1px 테두리(`hairline`), 16px 둥근 모서리, 패딩 20px.
- **`badge-pill`**: 둥근 알약 형태(`rounded-pill`), 13px(`text-xs`), 상태별 시맨틱 컬러 적용.

---

## InquAI UI 상세 규칙

- **대시보드 표현 규칙**:
  - 가장 중요한 카드 하나(답변 기한 초과)만 값이 있을 때 진하게 채우고, 누를 수 있는 카드는 오른쪽 위 `↗` 원형 표시.
  - 미처리처럼 '아직 남은 것'은 새 색 대신 빗금 무늬 (`url(#hatch-open)`, 범례도 같은 빗금).
  - '지금 가장 급한 문의' 카드 + 큰 [바로 처리] 버튼, '기한 임박 문의' 목록 (남은 시간 표시: 2시간 이내 노랑, 지나면 빨강).
  - 대시보드 유형 색에는 빨강·초록을 쓰지 않음 (배송 파랑, 주문 취소 주황, 교환 하늘, 반품·환불 노랑, 결제 분홍, 상품 보라, 쿠폰·적립금·회원 갈색, 기타 회색).
- **위쪽 검색창**: 모든 관리 화면에서 문의 번호·이메일·제목 검색 ('/' 키). 하나만 찾아지면 상세로 바로 이동, 여러 건이면 목록 표시.
- **고객 화면**:
  - 모든 페이지에 일관된 크기의 페이지 제목(`page-title`) + 한 줄 설명 적용. 본문 폭은 위쪽 메뉴와 동일한 `max-w-3xl`.
  - 문의 조회 및 내 쇼핑의 문의는 요약 카드(제목 · 답변 상태 · 마지막 글 한 줄)로 접고 가장 최근 문의만 펼침.
  - 상태는 고객 친화적 용어로 표기: **답변 준비 중**(파랑) / **답변 완료**(초록).
- **확인창 (ConfirmDialog)**:
  - 브라우저 기본 확인창(`window.confirm`) 대신 `ConfirmDialog` 컴포넌트 사용.
  - 흰 둥근 카드(`rounded-2xl`) + 흐린 배경 바탕. 버튼은 [취소](흰 바탕)와 [실행 동작 이름](파랑).
  - 되돌리기 어려운 작업(삭제, 비활성화, 강제 전송 등)은 빨간색 버튼과 느낌표(`!`) 경고 아이콘 적용.
- **상담원 공유 메모**:
  - 고객 대화 흐름과 완전히 분리하여 문의 상세 오른쪽 최상단 '상담원 공유 메모' 카드(`🔒 고객 비공개`)에 독립 배치.
  - 마지막 확인 이후 추가된 메모는 주황색 **New** 배지로 시각적 분리 제공.

---

## Do's and Don'ts

### Do
- 페이지 바탕은 푸른 라벤더/페리윙클 그라데이션을 항상 유지합니다.
- 본문 텍스트는 15px(`text-base`), 최소 글자 크기는 13px(`text-xs`) 원칙을 지킵니다.
- 버튼과 주요 선택 상태에는 일관되게 파란색(`primary: #4b5bd6`)을 사용합니다.
- 긴급도 '높음', '기한 초과' 등 즉각적인 조치가 필요한 요소에만 절제하여 빨간색을 사용합니다.
- 중요한 액션이나 정보는 한 화면 안에서 스크롤을 최소화하여 인지할 수 있도록 배치합니다.

### Don't
- 마케팅용 거대 폰트나 임의의 글자 크기(`text-[15px]` 등 시스템에 없는 크기)를 사용하지 않습니다.
- 불필요하게 어두운 배경(다크 네이비 푸터/사이드바)을 혼용하지 않습니다.
- 지나치게 강한 드롭 섀도우를 넣지 않고, 미세한 1px 테두리와 반투명 블러 판으로 깊이감을 표현합니다.
