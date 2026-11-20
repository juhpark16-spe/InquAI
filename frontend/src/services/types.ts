// FastAPI 응답 형식 (docs/api_spec.md). 서버 스키마(backend/schemas)와 맞춰 둡니다.

export const SENTIMENTS = ["긍정", "중립", "부정"] as const;
export const CATEGORIES = ["배송", "주문 취소", "교환", "반품·환불", "결제", "상품", "쿠폰·적립금·회원", "기타"] as const;
export const URGENCIES = ["높음", "보통", "낮음"] as const;
export const STATUSES = ["접수", "자동 처리", "검토 대기", "담당자 처리", "완료"] as const;
export const DECISIONS = ["자동 답변", "답변 초안", "담당자 연결"] as const;
export const MANUAL_STATUSES = ["검토 대기", "담당자 처리", "완료"] as const;

export type Role = "admin" | "agent";

export interface User {
  id: number;
  username: string;
  display_name: string;
  role: Role;
  must_change_password?: boolean; // 관리자가 정한 임시 비밀번호: 새 비밀번호를 정하기 전까지 다른 화면을 못 씀
}

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
  attachments: { url: string; filename: string; message_id: number | null }[]; // 30분짜리 사진 주소
  can_follow_up: boolean;
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
  customer_profile: { member: boolean; phone: string | null; orders: number; inquiries: number;
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
  customer_history: { id: number; inquiry_number: string; title: string; status: string; created_at: string }[];
  faq_titles: Record<string, string>;
  history: { at: string; actor: string; text: string; kind: "received" | "followup" | "ai" | "assign" | "status" | "draft" | "sent" | "correct" | "ticket" }[];
  due_at: string;
  overdue: boolean;
  messages: { id: number; text: string; created_at: string }[];
  notes: { id: number; author: string; text: string; created_at: string }[];
  attachments: { id: number; filename: string; content_type: string; size: number; message_id: number | null; created_at: string }[];
  notifications: { channel: string; recipient: string; subject: string; status: string; created_at: string }[];
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
  shipment_events?: { at: string; status: string; location: string | null }[];
  return_requested_at?: string | null;
  picked_up_at?: string | null;
  related_inquiries?: { id: number; inquiry_number: string; title: string; status: string; created_at: string }[];
  shipping_address?: string | null;
  option_choices?: { option: string; sold_out: boolean; current: boolean }[];
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
