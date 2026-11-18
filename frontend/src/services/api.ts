// FastAPI 통신 (기획서 6장 로그인 흐름)
// - 토큰은 HttpOnly 쿠키라 React가 읽거나 저장하지 않고, 브라우저가 자동으로 보냅니다.
// - 상태를 바꾸는 요청(POST·PUT·PATCH·DELETE)에는 csrf_token 쿠키 값을 X-CSRF-Token 헤더로 붙입니다.
// - 401(로그인 만료)을 받으면 /api/auth/refresh 를 한 번 시도하고, 성공하면 원래 요청을 다시 보냅니다.
import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";

import type {
  AgentLogPage, RetrainingStatus, FaqSuggestResult, ShopCustomer, ShopOrder, FaqAdmin, FaqPublic, FaqSearchTest, InquiryCreate, ResponseItem, InquiryCreated, InquiryDetail, InquiryListItem, InquiryPublic, InquiryState, Page, Role, User,
  UserDetail,
} from "./types";

export const http = axios.create({ baseURL: "/api", withCredentials: true });

const UNSAFE = new Set(["post", "put", "patch", "delete"]);

function readCookie(name: string): string | null {
  const hit = document.cookie.split("; ").find((c) => c.startsWith(`${name}=`));
  return hit ? decodeURIComponent(hit.slice(name.length + 1)) : null;
}

http.interceptors.request.use((config) => {
  if (UNSAFE.has((config.method ?? "get").toLowerCase())) {
    const csrf = readCookie("csrf_token");          // 관리자 로그인
    if (csrf) config.headers.set("X-CSRF-Token", csrf);
    const shopCsrf = readCookie("shop_csrf");       // 고객 로그인 (쇼핑몰 연동 시연, 따로 관리)
    if (shopCsrf) config.headers.set("X-Shop-CSRF", shopCsrf);
  }
  return config;
});

// 동시에 여러 요청이 401을 받아도 refresh 는 한 번만
let refreshing: Promise<void> | null = null;
const NO_REFRESH = ["/auth/login", "/auth/refresh", "/auth/logout", "/shop/"]; // 고객 로그인은 관리자 refresh와 무관

http.interceptors.response.use(undefined, async (error: AxiosError) => {
  const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;
  const isAuthUrl = NO_REFRESH.some((u) => config?.url?.startsWith(u));
  if (error.response?.status !== 401 || !config || config._retried || isAuthUrl || !readCookie("csrf_token")) {
    throw error;
  }
  config._retried = true;
  refreshing ??= http.post("/auth/refresh").then(() => undefined).finally(() => { refreshing = null; });
  await refreshing; // 실패하면 그대로 예외 → 화면에서 로그인 페이지로
  return http(config);
});

/** 서버 오류 응답({ detail, code })을 화면에 보여 줄 문장으로 */
export function errorMessage(err: unknown, fallback = "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return "입력 내용을 확인해 주세요."; // 422 (형식 오류)
    if (!err.response) return "서버에 연결할 수 없습니다.";
  }
  return fallback;
}

export function errorCode(err: unknown): string | undefined {
  return axios.isAxiosError(err) ? err.response?.data?.code : undefined;
}

// ---- Auth ----
export const authApi = {
  login: (username: string, password: string) =>
    http.post<{ user: User }>("/auth/login", { username, password }).then((r) => r.data.user),
  logout: () => http.post("/auth/logout"),
  me: () => http.get<User>("/auth/me").then((r) => r.data),
  changePassword: (current_password: string, new_password: string) =>
    http.post<{ user: User }>("/auth/change-password", { current_password, new_password }).then((r) => r.data.user),
};

// ---- 고객 ----
export const customerApi = {
  // 동기 방식: 분석·에이전트 처리가 끝날 때까지 기다림 (서버 제한 20초)
  create: (body: InquiryCreate) =>
    http.post<InquiryCreated>("/inquiries", body, { timeout: 30000 }).then((r) => r.data),
  lookup: (customer_email: string, password: string) =>
    http.post<{ items: InquiryPublic[]; notice: string }>("/inquiries/lookup", { customer_email, password }).then((r) => r.data),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return http.post<{ token: string; filename: string; size: number }>("/inquiries/uploads", form).then((r) => r.data);
  },
  followUp: (customer_email: string, password: string, inquiry_number: string, content: string, attachment_tokens: string[]) =>
    http.post<{ status: string; message: string }>("/inquiries/follow-up",
      { customer_email, password, inquiry_number, content, attachment_tokens }).then((r) => r.data),
  rate: (answerId: number, inquiry_number: string, customer_email: string, password: string, helpful: boolean) =>
    http.post<{ rating: number }>(`/inquiries/answers/${answerId}/rating`, { customer_email, password, helpful },
      { params: { inquiry_number } }).then((r) => r.data),
  faqs: () => http.get<FaqPublic[]>("/public/faqs").then((r) => r.data),
  suggestFaqs: (q: string, signal?: AbortSignal) =>
    http.get<FaqPublic[]>("/public/faqs/suggest", { params: { q }, signal }).then((r) => r.data),
};

// ---- 문의 관리 ----
export interface InquiryFilters {
  category?: string;
  urgency?: string;
  status?: string;
  decision?: string;
  open?: string;
  overdue?: string;
  assigned_to?: string;
  q?: string;
  sort?: "urgency" | "-created_at";
  page?: number;
  size?: number;
}

export const inquiryApi = {
  list: (filters: InquiryFilters) => {
    const params = Object.fromEntries(Object.entries(filters).filter(([, v]) => v !== "" && v !== undefined));
    return http.get<Page<InquiryListItem>>("/inquiries", { params }).then((r) => r.data);
  },
  get: (id: number) => http.get<InquiryDetail>(`/inquiries/${id}`).then((r) => r.data),
  assign: (id: number, assigned_to: number | null) =>
    http.patch<InquiryState>(`/inquiries/${id}/assign`, { assigned_to }).then((r) => r.data),
  setStatus: (id: number, status: string) =>
    http.patch<InquiryState>(`/inquiries/${id}/status`, { status }).then((r) => r.data),
  staff: () => http.get<User[]>("/admin/staff").then((r) => r.data),
  // 분류 결과 수정 (재학습 데이터): 바꿀 것만 보냄
  correctAnalysis: (id: number, body: { category?: string; sentiment?: string }) =>
    http.patch(`/inquiries/${id}/analysis`, body).then((r) => r.data),
  addNote: (id: number, text: string) => http.post(`/inquiries/${id}/notes`, { text }).then((r) => r.data),
  attachmentUrl: (inquiryId: number, attachmentId: number) => `/api/inquiries/${inquiryId}/attachments/${attachmentId}`,
  // 처리 대기열(미처리, 긴급도 → 오래된 순)에서 이전·다음 문의
  queue: (id: number) =>
    http.get<{ total: number; position: number | null; prev_id: number | null; next_id: number | null }>(`/inquiries/${id}/queue`)
      .then((r) => r.data),
  // 티켓 승인·반려 (취소 승인은 출고 전 주문만 → 주문 취소). 반려는 사유 필수
  decideTicket: (ticketId: number, status: "승인" | "반려", memo?: string) =>
    http.patch(`/tickets/${ticketId}`, { status, memo: memo || null }).then((r) => r.data),
};

// ---- 답변 (상담원 직접 작성·초안 수정·발송) ----
export const responseApi = {
  create: (inquiryId: number, text: string, send: boolean) =>
    http.post<ResponseItem>(`/inquiries/${inquiryId}/responses`, { text, send }).then((r) => r.data),
  update: (id: number, text: string) => http.put<ResponseItem>(`/responses/${id}`, { text }).then((r) => r.data),
  approve: (id: number, text?: string) =>
    http.post<ResponseItem>(`/responses/${id}/approve`, text === undefined ? undefined : { text }).then((r) => r.data),
  // AI 초안 만들기: 보내지 않은 초안 자리에 씀. 상담원이 고친 초안이 있으면 replace=true 일 때만 바꿈 (아니면 409)
  draft: (inquiryId: number, replace = false, instruction?: string) =>
    http.post<ResponseItem>(`/inquiries/${inquiryId}/draft`, { replace, instruction: instruction?.trim() || null }, { timeout: 30000 })
      .then((r) => r.data),
};

// ---- 대시보드 통계 (관리자) ----
export interface StatsSummary {
  range: { from: string; to: string; days: number };
  kpi: { total: number; today: number | null; auto_rate: number | null; approval_without_edit_rate: number | null };
  previous: { from: string; to: string; total: number; auto_rate: number | null; avg_latency_ms: number | null }; // 바로 앞 같은 길이 기간
  now: { open: number; urgent_open: number; review_waiting: number; unassigned_open: number; overdue_open: number };
  ratings: Record<"ai" | "agent", { up: number; down: number; satisfaction: number | null }>;
  daily: { date: string; total: number; open: number; done: number; auto: number; by_category: Record<string, number> }[];
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_urgency: Record<string, number>;
  by_decision: Record<string, number>;
  by_decided_by: Record<string, number>;
  ai: { avg_latency_ms: number | null; low_confidence: number; llm_calls: number; tokens: { input: number; output: number }; errors: number; draft_failures: number;
    corrections: { category: number; sentiment: number; by_category: Record<string, number> } };
  staff: { id: number; display_name: string; role: string; open: number; urgent_open: number }[];
}

export function kstDate(offsetDays = 0): string {
  const d = new Date(Date.now() + 9 * 3600 * 1000 - offsetDays * 86400 * 1000);
  return d.toISOString().slice(0, 10);
}

export interface ActivityItem {
  at: string;
  actor: string;
  text: string;
  kind: "received" | "followup" | "ai" | "assign" | "status" | "draft" | "sent" | "correct";
  inquiry_id: number;
  inquiry_number: string;
  title: string;
}

export const statsApi = {
  summary: (days: number) =>
    http.get<StatsSummary>("/stats/summary", { params: { from: kstDate(days - 1), to: kstDate(0) } }).then((r) => r.data),
  activity: (limit = 8) => http.get<ActivityItem[]>("/stats/activity", { params: { limit } }).then((r) => r.data),
  products: (days: number, limit = 5) =>
    http.get<ProductStats>("/stats/products", { params: { from: kstDate(days - 1), to: kstDate(0), limit } }).then((r) => r.data),
};

/** 상품별 문의 (주문에 연결된 문의만, 옵션이 달라도 같은 상품으로 묶음) */
export interface ProductStats {
  range: { from: string; to: string };
  total: number;
  linked: number;
  products: number;
  items: {
    product: string; count: number; by_category: Record<string, number>; top_category: string | null;
    negative: number; auto: number; hint: string | null;
    examples: { inquiry_id: number; inquiry_number: string; title: string; category: string | null }[];
  }[];
}

// ---- 계정 관리 (관리자) ----
export const userApi = {
  list: () => http.get<UserDetail[]>("/admin/users").then((r) => r.data),
  create: (body: { username: string; display_name: string; role: Role; password: string; categories: string[] }) =>
    http.post<UserDetail>("/admin/users", body).then((r) => r.data),
  update: (id: number, body: Partial<Pick<UserDetail, "display_name" | "role" | "is_active" | "categories">>) =>
    http.patch<UserDetail>(`/admin/users/${id}`, body).then((r) => r.data),
  resetPassword: (id: number, password: string) =>
    http.post<UserDetail>(`/admin/users/${id}/reset-password`, { password }).then((r) => r.data),
};

// ---- FAQ 관리 (관리자) ----
export interface FaqInput { category: string; question: string; answer: string }
export const faqApi = {
  list: () => http.get<FaqAdmin[]>("/faqs").then((r) => r.data),
  create: (body: FaqInput & { code?: string }) => http.post<FaqAdmin>("/faqs", body).then((r) => r.data),
  update: (id: number, body: FaqInput & { is_active: boolean }) => http.put<FaqAdmin>(`/faqs/${id}`, body).then((r) => r.data),
  deactivate: (id: number) => http.delete<FaqAdmin>(`/faqs/${id}`).then((r) => r.data),
  searchTest: (q: string) => http.get<FaqSearchTest>("/faqs/search-test", { params: { q } }).then((r) => r.data),
  // AI가 자동 답변하지 못한 비슷한 문의 묶음 → FAQ 초안 (LLM 호출이라 최대 수십 초)
  suggestions: (days = 30) => http.post<FaqSuggestResult>("/faqs/suggestions", { days }, { timeout: 90000 }).then((r) => r.data),
};

// ---- AI 실행 로그 (관리자 전체, 상담원은 배정된 문의만) ----
export interface AgentLogFilters {
  decision?: string; decided_by?: string; selected_tool?: string; tool_success?: string; problem?: string;
  inquiry_id?: number; from?: string; to?: string; page?: number; size?: number;
}
export const agentLogApi = {
  list: (filters: AgentLogFilters) => http.get<AgentLogPage>("/admin/agent-logs", { params: filters }).then((r) => r.data),
};

// ---- 쇼핑몰 로그인 연동 (고객, 시연용): 관리자 로그인과 쿠키를 따로 씀 ----
export const shopApi = {
  login: (email: string, password: string) => http.post<ShopCustomer>("/shop/login", { email, password }).then((r) => r.data),
  logout: () => http.post("/shop/logout"),
  me: () => http.get<ShopCustomer>("/shop/me").then((r) => r.data),
  orders: () => http.get<ShopOrder[]>("/shop/orders").then((r) => r.data),
  inquiries: () => http.get<{ items: InquiryPublic[]; notice: string }>("/shop/inquiries").then((r) => r.data),
  followUp: (inquiry_number: string, content: string, attachment_tokens: string[]) =>
    http.post<{ status: string; message: string }>(`/shop/inquiries/${inquiry_number}/follow-up`, { content, attachment_tokens })
      .then((r) => r.data),
  rate: (answerId: number, inquiry_number: string, helpful: boolean) =>
    http.post<{ rating: number }>(`/shop/answers/${answerId}/rating`, { helpful }, { params: { inquiry_number } }).then((r) => r.data),
};

// ---- 재학습 현황 (관리자) ----
export const retrainingApi = {
  status: () => http.get<RetrainingStatus>("/admin/retraining").then((r) => r.data),
};
