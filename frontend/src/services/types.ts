// FastAPI 응답 형식 (docs/api_spec.md). 서버 스키마(backend/schemas)와 맞춰 둡니다.

export const SENTIMENTS = ["긍정", "중립", "부정"] as const;
export const CATEGORIES = ["배송", "주문 취소", "교환", "반품·환불", "결제", "상품", "쿠폰·적립금·회원", "기타"] as const;
export const URGENCIES = ["높음", "보통", "낮음"] as const;
export const STATUSES = ["접수", "자동 처리", "검토 대기", "담당자 처리", "완료"] as const;
export const DECISIONS = ["자동 답변", "답변 초안", "담당자 연결"] as const;

export type Role = "admin" | "agent";

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  must_change_password?: boolean; // 관리자가 정한 임시 비밀번호: 새 비밀번호를 정하기 전까지 다른 화면을 못 씀
  open_count?: number;            // 배정·넘기기 상대 목록(/admin/staff): 지금 맡은 미처리
  urgent_open?: number;           //   그중 긴급
}

/** 배정·넘기기 목록의 이름: "김상담 · 상담원 · 미처리 3 (긴급 1)" */
export const staffLabel = (u: User) =>
  `${u.display_name} · ${u.role === "admin" ? "관리자" : "상담원"} · 미처리 ${u.open_count ?? 0}${u.urgent_open ? ` (긴급 ${u.urgent_open})` : ""}`;

export interface UserDetail extends User {
  categories: string[]; // 담당 유형 (빈 목록 = 전체 담당)
  is_active: boolean;
  locked_until: string | null;
  last_login_at: string | null;
  created_at: string;
}

export interface Assignee {
  id: number;
  display_name: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

// ---- 고객 ----
export interface FaqPublic {
  code: string;
  category: string;
  question: string;
  answer: string;
}

export interface InquiryCreate {
  customer_name: string;
  customer_email: string;
  order_number: string | null;
  title: string;
  content: string;
  password: string | null; // 쇼핑몰 로그인 고객은 비워도 됨 ('내 문의'에서 바로 봄)
  privacy_agreed: boolean;
  attachment_tokens: string[];
  // 파손·불량·오배송 문의: 사진 칸 이름(token → 송장/파손 부위), 고객이 고른 '파손 문의예요', '지금은 사진이 없어요'
  photo_labels?: Record<string, "송장" | "파손 부위">;
  damage_report?: boolean | null;   // 파손 체크: null = 내용으로 자동 판단
  client_request_id?: string;     // 이 화면에서 만든 값: 다시 눌러도 같은 문의 (중복 등록 방지)
  photos_later?: boolean;
}

export interface InquiryCreated {
  inquiry_number: string;
  status: string;
  answer: string | null;
  message: string;
}

export interface InquiryPublic {
  inquiry_number: string;
  title: string;
  content: string;
  status: string;
  answer: string | null;
  created_at: string;
  answered_at: string | null;
  answers: { id: number; text: string; answered_at: string; by: string; rating: number | null }[]; // 보낸 답변 전부 (시간순)
  messages: { id: number; text: string; at: string }[]; // 고객 추가 문의
  attachment_count: number;
  attachments: { url: string; filename: string; message_id: number | null; label?: string | null }[]; // 30분짜리 사진 주소 (label: 파손 문의의 송장·파손 부위)
  can_follow_up: boolean;
  more_answer_coming?: boolean; // 상담원이 확인 후 다시 안내하기로 함 → '추가 안내 예정'
  order_number?: string | null;  // 내 문의의 주문번호 (없으면 추가 문의에서 받음)
  order_needs_fix?: boolean;     // 적은 주문번호로 내 주문을 찾지 못함 → 추가 문의에서 다시 받음
  closed_note?: string | null;   // 답변 없이 종료된 문의 → '종료됨'과 이 문장
  photos_requested?: boolean;    // 파손 사진을 나중에 보내기로 함 → 추가 문의에 안내
}

// ---- 관리 ----
export interface InquiryListItem {
  id: number;
  inquiry_number: string;
  title: string;
  customer_name: string;
  status: string;
  category: string | null;
  urgency: string | null;
  sentiment: string | null;
  decision: string | null;
  confidence: number | null; // AI 유형 분류 확신도 (0~1)
  assigned_to: Assignee | null;
  created_at: string;
  due_at: string;
  overdue: boolean;
  recheck_note?: string | null;   // '확인 후 다시 안내' 표시: 확인할 내용
  recheck_due_at?: string | null; // 다시 안내할 기한
  note_count?: number;            // 상담원 공유 메모 개수
  new_follow_up?: boolean;        // 마지막 답변 뒤 고객 추가 문의
  bad_rating?: boolean;           // 보낸 답변에 고객 👎
}

/** 확인 후 다시 안내 표시 (backend/services/recheck.py) */
export interface Recheck {
  note: string;
  due_at: string;
  set_at: string | null;
  set_by: string;
  overdue: boolean;
}

export interface Analysis {
  category: string;
  confidence: number;
  sentiment: string;
  sentiment_confidence: number;
  urgency: string;
  route: string;
  decision: string | null;
  decided_by: string | null;
  decision_reason: string | null;
  scores: { category?: Record<string, number>; sentiment?: Record<string, number> } | null;
  model_version: string;
}

export interface ResponseItem {
  id: number;
  draft_text: string;
  final_text: string | null;
  generated_by: string;
  status: string;
  used_faq_ids: string[];
  grounded: boolean | null;
  is_edited: boolean;
  rating: number | null;
  check_points: string[] | null; // AI 초안에서 상담원이 확인할 것
  approved_by: number | null;
  approved_at: string | null;
  created_at: string;
}

export interface Ticket {
  id: number;
  ticket_type: string;
  order_id: number | null;
  reason: string;
  status: string;
  handled_by: number | null;
  handled_at: string | null;
  memo: string | null;     // 승인·반려 메모 (반려 사유)
  created_at: string;
}

export interface AgentLog {
  id: number;
  decision: string;
  decided_by: string;
  selected_tool: string | null;
  tool_success: boolean | null;
  tool_output: Record<string, unknown> | null;
  retrieved_faqs: [string, number][];
  used_faq_ids: string[];
  reason: string | null;
  response_text: string | null;
  llm_model: string | null;
  tokens: { input?: number; output?: number; calls?: number } | null;
  latency_ms: number | null;
  trace_url: string | null;
  error: string | null;
  steps: string[] | null; // 처리 경로 (LangGraph 노드)
  created_at: string;
}

export interface InquiryDetail {
  id: number;
  inquiry_number: string;
  customer: { name: string; email: string; order_number: string | null };
  // 고객 카드: 쇼핑몰 회원 여부, 전화번호(가림), 주문·문의 수, 불만 신호
  customer_profile: { customer_id?: number | null; member: boolean; phone: string | null; orders: number; inquiries: number;
    negative_inquiries: number; negative_ratings: number;
    points_balance: number | null; points_pending: number;
    point_history: { at: string; amount: number; reason: string; status: string; order_number: string | null }[];
    coupons: { name: string; benefit: string; min_amount: number; expires_at: string; used_at: string | null; state: string }[];
  } | null;
  title: string;
  content: string;
  status: string;
  assigned_to: Assignee | null;
  created_at: string;
  updated_at: string;
  analysis: Analysis | null;
  responses: ResponseItem[];
  tickets: Ticket[];
  agent_logs: AgentLog[];
  corrections: { id: number; field: string; before_label: string; after_label: string; created_at: string }[];
  order: OrderCard | null;
  email_orders: OrderCard[]; // 문의 이메일로 찾은 다른 주문 (본인 확인 필요)
  // 고객이 처음 글·추가 문의에 적은 다른 주문번호 (상담원이 [이 번호로 확인]으로 바로 적용)
  order_hints?: { order_number: string; found: boolean; email_match: boolean; product_name: string | null }[];
  customer_history: { id: number; inquiry_number: string; title: string; status: string; created_at: string }[];
  customer_history_hidden?: { total: number; open: number };   // 상담원: 다른 상담원이 맡은(또는 미배정) 같은 고객 문의 수
  faq_titles: Record<string, string>;
  history: { at: string; actor: string; text: string; kind: "received" | "followup" | "ai" | "assign" | "status" | "draft" | "sent" | "correct" | "ticket" | "recheck" | "mail" }[];
  due_at: string;
  overdue: boolean;
  recheck?: Recheck | null;
  photo_request?: string | null; // '나중에': 파손 문의인데 고객이 사진을 나중에 보내기로 함
  close_reason?: string | null;  // 답변 없이 종료한 사유
  messages: { id: number; text: string; created_at: string }[];
  notes: { id: number; author: string; author_id?: number | null; text: string; created_at: string }[];
  attachments: { id: number; filename: string; content_type: string; size: number; message_id: number | null; label?: string | null; created_at: string }[];
  // 고객 답변 알림 메일: 기록(메일 꺼짐) / 대기 / 발송 / 실패 / 건너뜀(예시 주소)
  notifications: { channel: string; recipient: string; subject: string; status: string; error?: string | null; sent_at?: string | null; created_at: string }[];
}

export interface OrderCard {
  found: boolean;
  order_number: string;
  email_match: boolean | null;
  orderer: string | null;
  product_name: string | null;
  amount: number | null;
  order_status: string | null;
  shipping_status: string | null;
  tracking_number: string | null;
  ordered_at: string | null;
  delivered_at: string | null;
  cancellable: boolean | null;
  return_until: string | null;
  returnable: boolean | null;
  defect_return_until: string | null;
  // 상담에 필요한 상세 (결제·수량·배송 추적·반품 진행·같은 주문의 다른 문의)
  quantity?: number | null;
  unit_price?: number | null;
  option?: string | null;
  payment_method?: string | null;
  paid_at?: string | null;
  payments?: { kind: string; status: string; method: string | null; amount: number; approval_no: string | null; at: string; memo: string | null }[];
  duplicate_payment?: boolean;
  carrier?: string | null;
  carrier_info?: { name: string; phone: string; tracking_url: string } | null;   // 택배사 대표번호·배송조회 바로가기
  driver?: { name: string; phone: string } | null;                                // 배송 출발 뒤 담당 기사 (연락처 가운데 가림)
  shipment_events?: { at: string; status: string; location: string | null }[];
  return_requested_at?: string | null;
  picked_up_at?: string | null;
  return_reason?: string | null;     // [반품 회수 접수]에서 고른 사유 (단순 변심 / 불량·오배송)
  refund_preview?: number;           // 반품 승인 시 환불 예정 금액 (단순 변심이면 왕복 배송비 차감)
  related_inquiries?: { id: number; inquiry_number: string; title: string; status: string; created_at: string; assigned_to?: number | null }[];
  shipping_address?: string | null;
  // 같은 상품의 옵션별 재고 (옵션 변경·교환 안내). low = 3개 이하, restock_at = 품절일 때 재입고 예정일
  option_choices?: { option: string; stock: number; sold_out: boolean; low: boolean; restock_at: string | null; current: boolean }[];
}

export interface InquiryState {
  id: number;
  inquiry_number: string;
  status: string;
  assigned_to: Assignee | null;
  updated_at: string;
}

// ---- FAQ 관리 (관리자) ----
export interface FaqAdmin {
  id: number;
  code: string;
  category: string;
  question: string;
  answer: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  used_count: number;          // AI 자동 답변·초안의 근거로 쓰인 횟수
  last_used_at: string | null;
}

export interface FaqSearchTest {
  engine: string | null;
  suggest_min_score: number | null;
  hits: { code: string; category: string; question: string; score: number; suggested: boolean }[];
}

// ---- AI 실행 로그 ----
export interface AgentLogRow extends AgentLog {
  inquiry_id: number;
  inquiry_number: string;
  inquiry_title: string;
  inquiry_status: string;
  category: string;
  confidence: number;
}

export interface AgentLogPage {
  total: number;
  page: number;
  size: number;
  summary: {
    count: number;
    by_decision: Record<string, number>;
    by_decided_by: Record<string, number>;
    by_tool: Record<string, { count: number; failed: number }>;
    errors: number;
    tool_failures: number;
    low_confidence: number;
    avg_latency_ms: number | null;
    max_latency_ms: number | null;
    tokens: { input: number; output: number; calls: number };
  };
  items: AgentLogRow[];
  faq_titles: Record<string, string>;
}

// ---- 쇼핑몰 로그인 연동 (고객, 시연용) ----
export interface ShopCustomer { name: string; email: string }
export interface ShopOrder {
  order_number: string;
  product_name: string;
  amount: number;
  order_status: string;
  shipping_status: string | null;
  ordered_at: string;
  delivered_at: string | null;
  inquiry_count: number;
}

// ---- FAQ 자동 추천 ----
export interface FaqSuggestion {
  count: number;
  category: string;
  question: string;
  answer: string;
  check_points: string[];
  drafted: boolean;
  with_staff_answer: number;
  nearest_faq: { code: string; question: string; score: number } | null;
  examples: { inquiry_id: number; inquiry_number: string; title: string; content: string }[];
}
export interface FaqSuggestResult { days: number; candidates: number; engine: string; items: FaqSuggestion[] }

// ---- 재학습 현황 ----
export interface ModelVersion {
  version: string;
  trained_at?: string;
  base_model?: string;
  data?: string;
  corrections_used?: number;
  scores: { external?: number; written_eval?: number; written_eval2?: number; real?: number };
  note?: string;
  current?: boolean;
}
export interface RetrainingStatus {
  model: ModelVersion;
  // 재학습 권장: 새 수정 50건 이상 또는 같은 패턴의 새 수정 10건 이상 (backend/api/retraining.py)
  recommend?: { needed: boolean; reasons: string[]; pending_threshold: number; pattern_threshold: number };
  corrections: { total: number; by_field: Record<string, number>; pending: number };
  patterns: { field: string; before: string; after: string; count: number; pending: number;
    examples: { inquiry_id: number; text: string }[] }[];
  recent: { id: number; inquiry_id: number; inquiry_number: string | null; field: string; before: string; after: string;
    text: string; at: string; pending: boolean }[];
  history: ModelVersion[];
}

/** AI 초안 수정 분석 (GET /api/stats/drafts): 상담원이 승인해 보낸 AI 초안과 보낸 답변 비교 */
export type DraftLevel = "그대로" | "조금 고침" | "많이 고침";
export type DraftKind = "덧붙임" | "줄임" | "고쳐 씀";
export interface DraftGroup { count: number; unedited: number; unedited_rate: number | null; avg_change: number | null }
export interface DraftStats {
  range: { from: string; to: string };
  summary: DraftGroup & {
    target: number;
    levels: Record<DraftLevel, number>;
    kinds: Record<DraftKind, number>;
    ai_share: number | null;            // 보낸 답변 글자 중 AI 초안에서 온 비율
    median_wait_min: number | null;     // 초안이 만들어진 뒤 보낼 때까지 (중앙값, 분)
    waiting: number;                    // 지금 검토를 기다리는 초안
  };
  by_category: (DraftGroup & { category: string })[];
  by_staff: (DraftGroup & { id: number; display_name: string })[];
  daily: { date: string; count: number; unedited: number }[];
  regenerate: { count: number; with_instruction: number; top_instructions: { text: string; count: number }[] };
  examples: {
    inquiry_id: number; inquiry_number: string; title: string; category: string; staff: string;
    level: DraftLevel; kind: DraftKind | null; change: number; added: number; removed: number; sent_at: string;
    segments: { op: "same" | "add" | "del"; text: string }[];
  }[];
}
