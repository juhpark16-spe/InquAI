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
  password: string;
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
  history: { at: string; actor: string; text: string; kind: "received" | "followup" | "ai" | "assign" | "status" | "draft" | "sent" | "correct" }[];
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
