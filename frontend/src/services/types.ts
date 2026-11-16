// FastAPI 응답 형식 (docs/api_spec.md). 서버 스키마(backend/schemas)와 맞춰 둡니다.

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
  assigned_to: Assignee | null;
  created_at: string;
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
}

export interface InquiryState {
  id: number;
  inquiry_number: string;
  status: string;
  assigned_to: Assignee | null;
  updated_at: string;
}
