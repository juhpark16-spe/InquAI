// 문의 상세 (/admin/inquiries/:id) — 상담원이 처리하는 순서대로 배치
//   상단 고정: 무엇을·얼마나 급하게 (제목, 긴급도, 상태, 경과 시간) + 바로 할 수 있는 처리 (담당자, 완료/다시 열기)
//   왜 왔나: AI가 사람에게 넘긴 이유
//   왼쪽(일하는 곳): 고객 문의 → 답변(작성·승인은 3주차) → 처리 이력
//   오른쪽(판단 근거, 25rem 고정 폭 → 일하는 곳이 넓게): 처리할 티켓 → 주문 정보(취소·반품 가능 여부) → 고객(누구인지·불만 신호)
//     → AI 분석 → 처리된 티켓 → AI 처리 상세(관리자, 접힘). 주문과 관계없는 문의(쿠폰·회원 등)는 고객을 먼저
//   카드는 흰 바탕 + 연한 테두리로 가볍게. 글씨: 구역 제목 17 · 왼쪽 본문 15 · 오른쪽 참고 정보 14px
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import AnalysisEditor from "../../components/AnalysisEditor";
import AnswerComposer from "../../components/AnswerComposer";
import { Alert, Badge, Button, Input, Select, Spinner, cx, formatDate } from "../../components/ui";
import { errorMessage, inquiryApi } from "../../services/api";
import type { AgentLog, InquiryDetail, OrderCard, User } from "../../services/types";

const OPEN = ["접수", "검토 대기", "담당자 처리"];
const LOW_CONFIDENCE = 0.8;
const FAQ_MIN_SCORE = 0.18; // backend/api/faqs_public.py SUGGEST_MIN_SCORE 와 같은 값

function timeAgo(iso: string) {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  if (min < 60 * 24) return `${Math.floor(min / 60)}시간 전`;
  return `${Math.floor(min / 1440)}일 전`;
}

function daysLeft(iso: string) {
  const d = Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000);
  return d >= 0 ? `D-${d}` : `${-d}일 지남`;
}

const won = (n: number | null) => (n === null ? "-" : `${n.toLocaleString()}원`);

/** 남은 답변 기한: 1시간 넘게 남으면 보통, 1시간 이내 주황, 지나면 빨강 (1분마다 다시 계산) */
function DueTime({ due, overdue, open }: { due: string; overdue: boolean; open: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);
  if (!open) return null;
  const left = new Date(due).getTime() - now;
  if (overdue || left <= 0) {
    return <span className="ml-2 rounded-full bg-rose-600 px-2 py-0.5 font-semibold text-white">⏰ 답변 기한 {Math.max(1, Math.round(-left / 3_600_000))}시간 지남</span>;
  }
  const mins = Math.round(left / 60_000);
  const label = mins < 60 ? `${mins}분 남음` : `${Math.floor(mins / 60)}시간 ${mins % 60 ? `${mins % 60}분 ` : ""}남음`;
  return (
    <span className={cx("ml-2 rounded-full px-2 py-0.5 font-medium", mins <= 60 ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600")}
      title={`답변 기한 ${formatDate(due)}`}>
      ⏱ 답변 기한 {label}
    </span>
  );
}

/** 상세 화면 카드: 흰 바탕 + 연한 테두리, 제목 줄 아래 얇은 선 (구역은 구분되되 상자가 내용보다 튀지 않게) */
function Card({ title, action, children }: { title: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-hairline bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-hairline px-5 py-3">
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        {action}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

/** 접을 수 있는 카드: 접힌 상태를 브라우저에 기억 (덜 보는 카드는 접어 두고 스크롤을 줄임) */
function Fold({ id, title, summary, children, defaultOpen = true }: {
  id: string; title: string; summary?: ReactNode; children: ReactNode; defaultOpen?: boolean;
}) {
  const key = `inquai.fold.${id}`;
  const [open, setOpen] = useState(() => {
    try {
      const v = localStorage.getItem(key);
      return v === null ? defaultOpen : v === "1";
    } catch {
      return defaultOpen;
    }
  });
  const toggle = () => {
    setOpen(!open);
    try { localStorage.setItem(key, open ? "0" : "1"); } catch { /* 저장 못 해도 동작 */ }
  };
  return (
    <section className="overflow-hidden rounded-2xl border border-hairline bg-white">
      <button type="button" onClick={toggle} aria-expanded={open}
        className={cx("flex w-full items-center justify-between gap-3 px-5 py-3 text-left hover:bg-surface-soft", open && "border-b border-hairline")}>
        <span className="text-lg font-semibold text-ink">{title}</span>
        <span className="flex min-w-0 items-center gap-2 text-sm text-muted">
          {!open && summary && <span className="truncate text-body">{summary}</span>}
          <span className="shrink-0">{open ? "접기 ▴" : "펼치기 ▾"}</span>
        </span>
      </button>
      {open && <div className="px-5 py-4">{children}</div>}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-ink">{children}</dd>
    </>
  );
}

/** 가능/불가를 색 있는 표시로 (초록 = 가능, 회색 = 불가) */
function YesNo({ ok, yes, no }: { ok: boolean | null; yes: string; no: string }) {
  if (ok === null) return <span className="text-slate-500">-</span>;
  return (
    <span className={cx("inline-block rounded-md px-2 py-0.5 text-sm font-semibold",
      ok ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700")}>
      {ok ? `✓ ${yes}` : `✕ ${no}`}
    </span>
  );
}

/** AI가 이 문의를 사람에게 넘긴 이유 (또는 자동 답변 완료) */
function DecisionBanner({ d }: { d: InquiryDetail }) {
  const a = d.analysis;
  if (!a) return <Alert kind="info">아직 AI 분석이 없습니다. 원문을 보고 직접 처리해 주세요.</Alert>;
  const log = d.agent_logs.at(-1);
  const style = a.decision === "자동 답변" ? "border-l-emerald-500"
    : a.urgency === "높음" ? "border-l-rose-500" : "border-l-amber-500";
  const title = a.decision === "자동 답변" ? "AI가 FAQ를 근거로 자동 답변을 보냈습니다"
    : a.decision === "담당자 연결" ? "AI가 담당자에게 넘긴 문의입니다" : "AI가 상담원 검토가 필요하다고 판단했습니다";
  // 긴급 표시는 제목 옆에 이미 있고, 판단 방식·처리 경로는 'AI 처리 상세'(관리자)에서 봄 → 여기서는 이유 한 줄만
  const reason = a.decision_reason?.replace(/\s*\((규칙|LLM)\)\s*$/, "");
  return (
    <div className={cx("rounded-xl border border-l-4 border-hairline bg-white px-4 py-2.5 text-sm", style)}>
      <span className="font-semibold text-ink">{title}</span>
      {reason && <span className="text-body"> · {reason}</span>}
      {log?.error && <span className="text-rose-700"> · AI 처리 중 오류가 있어 상담원에게 넘어왔습니다</span>}
    </div>
  );
}

/** 주문 한 건의 상세: 상태·배송·취소·반품 가능 기한 */
function OrderRows({ o }: { o: OrderCard }) {
  return (
    <dl className="grid grid-cols-[5.5rem_1fr] items-center gap-x-3 gap-y-1.5 text-sm">
      <Row label="주문 상태"><Badge value={o.order_status} /></Row>
      <Row label="배송">{o.shipping_status ?? "-"}</Row>
      {o.tracking_number && <Row label="송장번호"><span className="font-mono font-semibold">{o.tracking_number}</span></Row>}
      <Row label="주문일">{formatDate(o.ordered_at)}</Row>
      {o.delivered_at && <Row label="배송 완료">{formatDate(o.delivered_at)}</Row>}
      <Row label="취소">
        {o.order_status === "취소" ? <span className="font-semibold text-slate-700">이미 취소된 주문</span>
          : <YesNo ok={o.cancellable} yes="가능 (출고 전)" no="불가 (출고됨)" />}
      </Row>
      <Row label="반품·교환">
        {/* 기한은 쇼핑몰 정책 기준 (단순 변심 7일, 불량·오배송 30일) */}
        {o.return_until ? (
          <span>
            <YesNo ok={o.returnable} yes={`가능 ${daysLeft(o.return_until)}`} no="단순 변심 기한 지남" />
            {!o.returnable && o.defect_return_until && (
              <span className="mt-1 block text-xs text-muted">불량·오배송은 {daysLeft(o.defect_return_until)}</span>
            )}
          </span>
        ) : <span className="text-slate-600">배송 완료 후 판단</span>}
      </Row>
    </dl>
  );
}

/** 상품명 + 주문번호·금액 (주문 정보의 머리글) */
function OrderHead({ o }: { o: OrderCard }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-base font-semibold text-ink">{o.product_name}</p>
      <p className="text-sm text-muted">
        <span className="font-mono text-body">{o.order_number}</span> · {won(o.amount)}
      </p>
    </div>
  );
}

/** 주문 정보: 고객이 적은 주문(크게) + 문의 이메일로 찾은 다른 주문(핵심만 보이고 누르면 상세) */
function OrderInfo({ o, others }: { o: OrderCard | null; others: OrderCard[] }) {
  return (
    <Card title="주문 정보">
      {!o && <p className="text-sm text-muted">고객이 주문번호를 적지 않았습니다.</p>}
      {o && !o.found && (
        <Alert>주문번호 <b className="font-mono">{o.order_number}</b>를 찾을 수 없습니다. 고객에게 주문번호를 다시 확인해 주세요.</Alert>
      )}
      {o?.found && (
        <>
          {o.email_match === false && (
            <div className="mb-3"><Alert>문의 이메일과 주문자 이메일이 다릅니다 (주문자: {o.orderer}). 본인 확인 전에는 주문 정보를 안내하지 마세요.</Alert></div>
          )}
          <div className="mb-3">
            <p className="mb-0.5 text-xs font-semibold text-emerald-700">고객이 문의한 주문</p>
            <OrderHead o={o} />
          </div>
          <OrderRows o={o} />
        </>
      )}

      {others.length > 0 ? (
        <details className={cx("group/others", o?.found && "mt-4 border-t border-hairline pt-3")} open={!o?.found}>
          <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold text-body hover:text-primary">
            {o?.found ? `이 고객의 다른 주문 (${others.length})` : `문의 이메일로 찾은 주문 (${others.length})`}
            <span className="font-normal text-muted"><span className="group-open/others:hidden">펼치기 ▾</span><span className="hidden group-open/others:inline">접기 ▴</span></span>
          </summary>
          {!o?.found && (
            <p className="mt-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              주문번호 없이 이메일로 찾은 주문입니다. 어떤 주문인지, 본인이 맞는지 고객에게 확인한 뒤 안내하세요.
            </p>
          )}
          <ul className="mt-2 space-y-2">
            {others.map((x) => (
              <li key={x.order_number}>
                <details className="group rounded-xl border border-hairline bg-white">
                  <summary className="flex cursor-pointer list-none items-start gap-3 px-3 py-2.5 hover:bg-surface-soft">
                    <div className="min-w-0 flex-1">
                      <OrderHead o={x} />
                      <p className="mt-0.5 text-xs text-muted">
                        {x.shipping_status ?? "배송 정보 없음"} · 주문 {formatDate(x.ordered_at)}
                      </p>
                    </div>
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <Badge value={x.order_status} />
                      <span className="text-xs text-muted"><span className="group-open:hidden">상세 ▾</span><span className="hidden group-open:inline">접기 ▴</span></span>
                    </span>
                  </summary>
                  <div className="border-t border-hairline px-3 py-2.5">
                    <OrderRows o={x} />
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </details>
      ) : !o?.found && (
        <p className="mt-1 text-sm text-muted">이 이메일로 된 주문도 없습니다.</p>
      )}
    </Card>
  );
}

const TICKET_ACTIONABLE = ["취소", "교환", "환불"];

/** 접수된 티켓: 취소·교환·환불은 상담원이 승인·반려 (취소 승인 → 주문 취소, 출고된 주문은 서버가 막음) */
function Tickets({ data, onChanged }: { data: InquiryDetail; onChanged: (msg: string) => void }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [memo, setMemo] = useState("");
  const [error, setError] = useState("");

  async function decide(id: number, status: "승인" | "반려", note?: string) {
    setError("");
    setBusy(id);
    try {
      await inquiryApi.decideTicket(id, status, note);
      setRejecting(null);
      setMemo("");
      onChanged(status === "승인"
        ? "티켓을 승인했습니다. [AI 초안 다시 만들기]를 누르면 처리 결과를 넣은 답변 초안을 받을 수 있어요."
        : "티켓을 반려했습니다. 반려 사유를 고객에게 안내해 주세요 (AI 초안 다시 만들기에 사유가 반영됩니다).");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const o = data.order;
  return (
    <Card title="접수된 티켓">
      <ul className="space-y-3 text-sm">
        {data.tickets.map((t) => {
          const actionable = TICKET_ACTIONABLE.includes(t.ticket_type) && t.status === "접수";
          const cancelBlocked = t.ticket_type === "취소" && o?.found && o.cancellable === false;
          return (
            <li key={t.id} className={cx("rounded-xl border p-3", actionable ? "border-amber-300 bg-amber-50/60" : "border-hairline")}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-ink">#{t.id} {t.ticket_type}</span>
                <Badge value={t.status} />
              </div>
              {t.memo && <p className="mt-1 text-sm text-slate-600">메모: {t.memo}</p>}
              {t.handled_at && <p className="mt-0.5 text-sm text-slate-500">{formatDate(t.handled_at)} 처리</p>}
              {actionable && (
                <div className="mt-2 space-y-2">
                  {t.ticket_type === "취소" && o?.found && (
                    <p className={cx("text-sm", cancelBlocked ? "text-rose-700" : "text-emerald-700")}>
                      {cancelBlocked ? `주문이 '${o.order_status}' 상태라 취소할 수 없어요 → 반려하고 반품으로 안내`
                        : `출고 전(${o.order_status})이라 승인하면 주문이 바로 취소됩니다`}
                    </p>
                  )}
                  {rejecting === t.id ? (
                    <div className="space-y-2">
                      <Input autoFocus placeholder="반려 사유 (예: 이미 출고되어 반품으로 안내)" maxLength={500}
                        value={memo} onChange={(e) => setMemo(e.target.value)} />
                      <div className="flex gap-2">
                        <Button variant="danger" className="min-h-9 flex-1 px-3 py-1" disabled={busy === t.id || !memo.trim()}
                          onClick={() => decide(t.id, "반려", memo)}>{busy === t.id ? <Spinner /> : "반려"}</Button>
                        <Button variant="ghost" className="min-h-9 px-3 py-1" onClick={() => { setRejecting(null); setMemo(""); }}>취소</Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex gap-2">
                      <Button className="min-h-9 flex-1 px-3 py-1" disabled={busy === t.id || !!cancelBlocked}
                        onClick={() => decide(t.id, "승인")}>{busy === t.id ? <Spinner /> : `${t.ticket_type} 승인`}</Button>
                      <Button variant="ghost" className="min-h-9 flex-1 px-3 py-1" disabled={busy === t.id}
                        onClick={() => setRejecting(t.id)}>반려</Button>
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {error && <div className="mt-2"><Alert>{error}</Alert></div>}
    </Card>
  );
}

function AiDetails({ log, faqTitles }: { log: AgentLog | undefined; faqTitles: Record<string, string> }) {
  if (!log) return null;
  return (
    <details className="group rounded-2xl border border-hairline bg-white">
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-lg font-semibold text-ink hover:bg-surface-soft">
        AI 처리 상세 <span className="text-sm font-normal text-slate-500">점검용 · 펼치기 <span className="inline-block transition group-open:rotate-180">⌄</span></span>
      </summary>
      <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1.5 border-t border-hairline px-5 py-3 text-sm">
        {log.steps && log.steps.length > 0 && <Row label="처리 경로">{log.steps.join(" → ")}</Row>}
        {log.trace_url && (
          <Row label="추적">
            <a href={log.trace_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
              LangSmith에서 단계별로 보기 ↗
            </a>
          </Row>
        )}
        <Row label="사용한 도구">{log.selected_tool ?? "-"} {log.tool_success === false && <span className="text-rose-700">(실패)</span>}</Row>
        <Row label="검색된 FAQ">
          {log.retrieved_faqs.length ? (
            <ul className="space-y-0.5">
              {log.retrieved_faqs.map(([code, s]) => (
                <li key={code} className="text-sm"><span className="font-mono">{code}</span> {faqTitles[code] ?? ""} <span className="text-slate-500">유사도 {s.toFixed(2)}</span></li>
              ))}
            </ul>
          ) : "-"}
        </Row>
        <Row label="LLM">{log.llm_model ?? "사용 안 함 (규칙 판단)"}</Row>
        <Row label="토큰">{log.tokens?.calls ? `입력 ${log.tokens.input} · 출력 ${log.tokens.output} (${log.tokens.calls}회)` : "-"}</Row>
        <Row label="처리 시간">{log.latency_ms !== null ? `${(log.latency_ms / 1000).toFixed(1)}초` : "-"}</Row>
        {log.error && <Row label="오류"><span className="break-all text-rose-700">{log.error}</span></Row>}
        <Row label="도구 원본">
          {log.tool_output ? <pre className="overflow-x-auto rounded bg-slate-50 p-2 text-sm">{JSON.stringify(log.tool_output, null, 2)}</pre> : "-"}
        </Row>
      </dl>
    </details>
  );
}

export default function InquiryDetailPage() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const [data, setData] = useState<InquiryDetail | null>(null);
  const [staff, setStaff] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [queue, setQueue] = useState<{ total: number; position: number | null; prev_id: number | null; next_id: number | null } | null>(null);
  const navigate = useNavigate();

  const load = useCallback(() => {
    inquiryApi.get(id).then(setData).catch((err) => setError(errorMessage(err)));
  }, [id]);
  useEffect(load, [load]);
  // 다른 문의로 옮기면 안내 문구를 지움
  useEffect(() => { setNotice(""); setActionError(""); }, [id]);
  // 단축키 Alt+← / Alt+→ : 이전·다음 미처리 문의
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || !queue) return;
      const to = e.key === "ArrowLeft" ? queue.prev_id : e.key === "ArrowRight" ? queue.next_id : null;
      if (to) { e.preventDefault(); navigate(`/admin/inquiries/${to}`); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queue, navigate]);
  // 처리 대기열 위치: 상태가 바뀔 때마다 다시 (완료하면 대기열에서 빠지고 '다음 미처리'가 바뀜)
  useEffect(() => {
    inquiryApi.queue(id).then(setQueue).catch(() => setQueue(null));
  }, [id, data?.status]);
  useEffect(() => {
    if (user?.role === "admin") inquiryApi.staff().then(setStaff).catch(() => setStaff([]));
  }, [user]);

  async function run(action: () => Promise<unknown>) {
    setActionError("");
    setBusy(true);
    try {
      await action();
      load();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <p className="p-6 text-center text-slate-600"><Spinner /></p>;

  const a = data.analysis;
  const log = data.agent_logs.at(-1);
  const isOpen = OPEN.includes(data.status);
  const lowConf = !!a && a.confidence < LOW_CONFIDENCE;
  const topScores = Object.entries(a?.scores?.category ?? {}).sort((x, y) => y[1] - x[1]).slice(0, 3);
  // 검색 점수가 낮은 FAQ는 관계없는 경우가 많아 참고 목록에서 뺌 (고객 화면 추천과 같은 기준)
  const refFaqs = (log?.retrieved_faqs ?? []).filter(([, s]) => s >= FAQ_MIN_SCORE);
  const p = data.customer_profile;
  const warn = !!p && (p.negative_ratings > 0 || p.negative_inquiries >= 2);
  const pendingTickets = data.tickets.some((t) => TICKET_ACTIONABLE.includes(t.ticket_type) && t.status === "접수");

  // 고객 카드: 누구인지·불만 신호·이 고객의 다른 문의 (다른 문의는 3건까지 보이고 나머지는 접음)
  const history = data.customer_history;
  const historyRow = (h: (typeof history)[number]) => (
    <li key={h.id} className="flex items-center justify-between gap-2">
      <Link to={`/admin/inquiries/${h.id}`} className="truncate text-primary hover:underline">{h.title}</Link>
      <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted"><Badge value={h.status} />{timeAgo(h.created_at)}</span>
    </li>
  );
  const customerCard = (
    <Fold id="customer" title="고객" summary={`${data.customer.name}${p ? ` · 문의 ${p.inquiries}건` : ""}${warn ? " · ⚠ 불만 신호" : ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-base font-semibold text-ink">{data.customer.name}</span>
        <span className={cx("rounded-full px-2 py-0.5 text-xs font-medium", p?.member ? "bg-primary-soft text-primary" : "bg-slate-100 text-slate-600")}>
          {p?.member ? "쇼핑몰 회원" : "비회원 문의"}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-[3.5rem_1fr] gap-x-3 gap-y-1 text-sm">
        <Row label="이메일"><span className="break-all">{data.customer.email}</span></Row>
        {p?.phone && <Row label="전화">{p.phone}</Row>}
        {p && <Row label="이력">주문 {p.orders}건 · 문의 {p.inquiries}건</Row>}
      </dl>
      {warn && (
        <p className="mt-2 rounded-lg bg-amber-50 px-3 py-1.5 text-sm text-amber-900">
          ⚠ 응대에 신경 쓸 고객:
          {p!.negative_ratings > 0 && <> 이전 답변에 👎 {p!.negative_ratings}번</>}
          {p!.negative_ratings > 0 && p!.negative_inquiries >= 2 && " ·"}
          {p!.negative_inquiries >= 2 && <> 불만 문의 {p!.negative_inquiries}건</>}
        </p>
      )}
      <div className="mt-3 border-t border-hairline pt-3">
        <p className="mb-1.5 text-sm font-semibold text-body">이 고객의 다른 문의 {history.length ? `(${history.length})` : ""}</p>
        {history.length === 0 ? <p className="text-sm text-muted">없음</p> : (
          <>
            <ul className="space-y-1.5 text-sm">{history.slice(0, 3).map(historyRow)}</ul>
            {history.length > 3 && (
              <details className="group/more mt-1.5">
                <summary className="cursor-pointer list-none text-sm text-muted hover:text-primary">
                  <span className="group-open/more:hidden">{history.length - 3}건 더 보기 ▾</span><span className="hidden group-open/more:inline">접기 ▴</span>
                </summary>
                <ul className="mt-1.5 space-y-1.5 text-sm">{history.slice(3).map(historyRow)}</ul>
              </details>
            )}
          </>
        )}
      </div>
    </Fold>
  );
  const orderCard = <OrderInfo o={data.order} others={data.email_orders} />;
  // 주문 관련 문의(주문번호를 적었거나 이메일로 찾은 주문이 있음)는 주문 정보가 판단의 핵심 → 위에. 아니면 고객을 위에
  const orderFirst = !!data.order || data.email_orders.length > 0;

  return (
    <div className="space-y-4">
      {/* 상단 고정: 무엇을, 얼마나 급하게 + 바로 할 수 있는 처리.
          본문 판 위쪽에 딱 맞게 (판의 안쪽 여백만큼 바깥으로 넓혀 판 모서리와 맞춤), 스크롤하면 위쪽 판(검색·내 정보) 바로 아래에 붙음 */}
      <div className="sticky top-[var(--admin-header-bottom)] z-10 -mx-4 -mt-4 rounded-t-2xl border-b border-hairline bg-surface-soft/95 px-4 py-3 backdrop-blur lg:-mx-6 lg:-mt-6 lg:rounded-t-3xl lg:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <Link to="/admin/inquiries" className="inline-flex items-center gap-1 text-sm text-muted hover:text-primary">← 문의 목록</Link>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              <h1 className="page-title truncate">{data.title}</h1>
              {a?.urgency === "높음" && <span className="rounded-full bg-rose-600 px-2 py-0.5 text-sm font-semibold text-white">⚠ 긴급</span>}
              <Badge value={data.status} />
            </div>
            <p className="mt-1 flex flex-wrap items-center gap-y-1 text-sm text-muted">
              <span className="font-mono font-medium text-body">{data.inquiry_number}</span>
              <span className="mx-1.5">·</span>접수 {timeAgo(data.created_at)} ({formatDate(data.created_at)})
              <DueTime due={data.due_at} overdue={data.overdue} open={isOpen} />
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {queue && queue.total > 0 && (
              <span className="flex items-center gap-1" aria-label="처리 대기열">
                <Button variant="ghost" className="min-h-9 px-2.5 py-1" disabled={!queue.prev_id} title="이전 미처리 문의 (Alt+←)"
                  onClick={() => queue.prev_id && navigate(`/admin/inquiries/${queue.prev_id}`)}>◀</Button>
                <span className="px-1 tabular-nums text-muted" title="미처리 대기열 (긴급도 → 오래된 순)">
                  {queue.position ? `${queue.position} / ${queue.total}` : `대기 ${queue.total}건`}
                </span>
                <Button variant="ghost" className="min-h-9 px-2.5 py-1" disabled={!queue.next_id} title="다음 미처리 문의 (Alt+→)"
                  onClick={() => queue.next_id && navigate(`/admin/inquiries/${queue.next_id}`)}>▶</Button>
              </span>
            )}
            <span className="ml-1 text-muted">담당</span>
            {user?.role === "admin" ? (
              <Select disabled={busy} value={data.assigned_to?.id ?? ""} aria-label="담당자"
                onChange={(e) => run(() => inquiryApi.assign(id, e.target.value ? Number(e.target.value) : null))}>
                <option value="">미배정</option>
                {staff.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
              </Select>
            ) : (
              <span className="font-medium text-ink">{data.assigned_to?.display_name ?? "미배정"}</span>
            )}
            {isOpen ? (
              <Button disabled={busy} onClick={() => run(() => inquiryApi.setStatus(id, "완료"))}>완료 처리</Button>
            ) : (
              <Button variant="ghost" disabled={busy} onClick={() => run(() => inquiryApi.setStatus(id, "담당자 처리"))}>다시 열기</Button>
            )}
          </div>
        </div>
        {actionError && <div className="mt-2"><Alert>{actionError}</Alert></div>}
        {notice && <div className="mt-2"><Alert kind="success">{notice}</Alert></div>}
        {/* 처리가 끝난 문의: 다음 미처리 문의로 바로 (목록으로 돌아갔다 오지 않게) */}
        {!isOpen && queue?.next_id && (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
            <span>이 문의는 처리됐어요. 미처리 {queue.total}건이 남아 있습니다.</span>
            <Button className="min-h-9 px-4 py-1" onClick={() => navigate(`/admin/inquiries/${queue.next_id}`)}>다음 미처리 문의 →</Button>
          </div>
        )}
      </div>

      <DecisionBanner d={data} />

      {/* 왼쪽(일하는 곳)이 넓게: 오른쪽 참고 정보는 고정 폭 (lg 22rem, xl 25rem) */}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_25rem]">
        {/* 왼쪽: 일하는 곳 */}
        <div className="space-y-4">
          <Card title="문의와 답변">
            <AnswerComposer data={data} refFaqCodes={refFaqs.map(([code]) => code)} onChanged={load} />
          </Card>

          <details className="group rounded-2xl border border-hairline bg-white">
            <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-lg font-semibold text-ink hover:bg-surface-soft">
              전체 처리 이력 <span className="text-sm font-normal text-muted">배정·상태 변경·알림 포함 · <span className="group-open:hidden">펼치기 ▾</span><span className="hidden group-open:inline">접기 ▴</span></span>
            </summary>
            <div className="border-t border-hairline px-5 py-4">
            <ol className="relative space-y-3 border-l border-hairline pl-4">
              {data.history.map((e, i) => (
                <li key={i} className="text-sm">
                  <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-slate-300" />
                  <span className="text-xs text-muted">{formatDate(e.at)} · {e.actor}</span>
                  <p className="text-body">{e.text}</p>
                </li>
              ))}
            </ol>
            </div>
          </details>
        </div>

        {/* 오른쪽: 판단 근거 */}
        <div className="space-y-4">
          {/* 처리할 티켓이 있으면 맨 위에 (상담원이 가장 먼저 할 일) */}
          {pendingTickets && <Tickets data={data} onChanged={(m) => { setNotice(m); load(); }} />}
          {orderFirst ? <>{orderCard}{customerCard}</> : <>{customerCard}{orderCard}</>}

          {/* 요약 줄(유형·확신도·감정·긴급도)만으로 충분해 접어 둠. 확신도가 낮으면 유형을 확인해야 하니 펼침 */}
          <Fold id="analysis" title="AI 분석" defaultOpen={lowConf} summary={a ? `${a.category} ${(a.confidence * 100).toFixed(0)}%${lowConf ? " ⚠ 유형 확인 필요" : ""} · ${a.sentiment} · 긴급도 ${a.urgency}` : "분석 전"}>
            {!a ? <p className="text-sm text-muted">분석 전</p> : (
              <>
                <dl className="grid grid-cols-[3.5rem_1fr] items-center gap-x-3 gap-y-1.5 text-sm">
                  <Row label="유형">
                    <span className="font-semibold">{a.category}</span>{" "}
                    <span className={cx(lowConf ? "font-semibold text-rose-700" : "text-muted")}>
                      확신도 {(a.confidence * 100).toFixed(0)}%{lowConf && " · 낮음, 유형 확인 필요"}
                    </span>
                  </Row>
                  <Row label="감정"><Badge value={a.sentiment} /></Row>
                  <Row label="긴급도"><Badge value={a.urgency} /></Row>
                </dl>
                <details className="mt-3" open={lowConf}>
                  <summary className="cursor-pointer text-sm text-muted hover:text-primary">다른 유형 후보</summary>
                  <div className="mt-2 space-y-1">
                    {topScores.map(([label, p]) => (
                      <div key={label} className="flex items-center gap-2 text-sm">
                        <span className="w-24 truncate text-muted">{label}</span>
                        <div className="h-1.5 flex-1 rounded bg-slate-100"><div className="h-1.5 rounded bg-indigo-400" style={{ width: `${Math.round(p * 100)}%` }} /></div>
                        <span className="w-9 text-right tabular-nums text-muted">{(p * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-muted">모델 {a.model_version}</p>
                </details>
                <AnalysisEditor key={`${a.category}-${a.sentiment}`} data={data} onSaved={load} />
              </>
            )}
          </Fold>

          {!pendingTickets && data.tickets.length > 0 && <Tickets data={data} onChanged={(m) => { setNotice(m); load(); }} />}

          {/* 도구·토큰·처리 시간 등 점검용 정보는 관리자에게만 */}
          {user?.role === "admin" && <AiDetails log={log} faqTitles={data.faq_titles} />}
        </div>
      </div>
    </div>
  );
}
