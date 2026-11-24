// 문의 상세 (/admin/inquiries/:id) — 상담원이 처리하는 순서대로 배치
//   상단 고정: 무엇을·얼마나 급하게 (제목, 긴급도, 상태, 경과 시간) + 바로 할 수 있는 처리 (담당자, 완료/다시 열기)
//   왜 왔나: AI가 사람에게 넘긴 이유
//   왼쪽(일하는 곳): 고객 문의 → 답변(작성·승인은 3주차) → 처리 이력
//   오른쪽(판단 근거, 25rem 고정 폭 → 일하는 곳이 넓게): 처리할 티켓 → 주문 정보(취소·반품 가능 여부) → 고객(누구인지·불만 신호)
//     → AI 분석 → 처리된 티켓 → AI 처리 상세(관리자, 접힘). 주문과 관계없는 문의(쿠폰·회원 등)는 고객을 먼저
//   카드는 흰 바탕 + 연한 테두리로 가볍게. 글씨: 구역 제목 17 · 왼쪽 본문 15 · 오른쪽 참고 정보 14px
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import AnalysisEditor from "../../components/AnalysisEditor";
import AnswerComposer from "../../components/AnswerComposer";
import InternalNotes from "../../components/InternalNotes";
import { confirmDialog } from "../../components/ConfirmDialog";
import Modal from "../../components/Modal";
import { TOOL_LABEL, byLabel, failReason, toolLabel } from "../../services/labels";
import { Alert, Badge, Button, Input, Select, Spinner, cx, formatDate } from "../../components/ui";
import { errorMessage, inquiryApi, type QuickAction } from "../../services/api";
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
const ORDER_CATEGORIES = ["배송", "주문 취소", "교환", "반품·환불", "결제"];   // 주문을 확인해야 상담할 수 있는 유형
const ORDER_NUMBER_ASK = "정확한 확인을 위해 주문번호(예: 20261103-0042)를 알려 주시겠어요? 마이페이지 > 주문내역에서 확인하실 수 있습니다.";

/** 답변 칸에 문장 넣기 (주문 정보 카드의 버튼 → AnswerComposer 가 받아 커서 자리에 넣음) */
export function insertIntoReply(text: string) {
  window.dispatchEvent(new CustomEvent("inquai:insert-reply", { detail: text }));
}

const shortDate = (iso: string | null | undefined) => (iso ? formatDate(iso) : "-");

/** 환불 진행: 결제 내역의 환불 줄 (예정이면 날짜, 예정일이 지났으면 빨강) */
function RefundLine({ o }: { o: OrderCard }) {
  const refunds = (o.payments ?? []).filter((p) => p.kind === "환불");
  if (!o.return_requested_at && refunds.length === 0) return null;
  const now = Date.now();
  return (
    <>
      {o.return_requested_at && (
        <Row label="반품 진행">
          접수 {shortDate(o.return_requested_at)}
          {o.picked_up_at ? <> → 회수 완료 {shortDate(o.picked_up_at)}</> : <span className="text-amber-700"> → 회수 전</span>}
        </Row>
      )}
      {refunds.map((r, i) => {
        const late = r.status === "예정" && new Date(r.at).getTime() < now;
        return (
          <Row key={i} label="환불">
            <span className={cx("font-semibold", r.status === "완료" ? "text-emerald-700" : late ? "text-rose-700" : "text-amber-700")}>
              {r.status === "완료" ? "완료" : late ? "예정일 지남" : "예정"} {won(r.amount)}
            </span>
            <span className="text-muted"> · {shortDate(r.at)}</span>
            {r.memo && <span className="block text-xs text-muted">{r.memo}</span>}
          </Row>
        );
      })}
    </>
  );
}

/** 주문 한 건의 상세: 상태·결제·배송·반품·환불·취소/반품 가능 기한 */
function OrderRows({ o }: { o: OrderCard }) {
  return (
    <dl className="grid grid-cols-[5.5rem_1fr] items-center gap-x-3 gap-y-1.5 text-sm">
      <Row label="주문 상태"><Badge value={o.order_status} /></Row>
      <Row label="배송">
        {o.shipping_status ?? "-"}
        {o.carrier && <span className="text-muted"> · {o.carrier}</span>}
      </Row>
      {o.tracking_number && <Row label="송장번호"><span className="font-mono font-semibold">{o.tracking_number}</span></Row>}
      {o.payment_method && <Row label="결제">{o.payment_method} <span className="text-muted">· {shortDate(o.paid_at)}</span></Row>}
      <Row label="주문일">{formatDate(o.ordered_at)}</Row>
      {o.delivered_at && <Row label="배송 완료">{formatDate(o.delivered_at)}</Row>}
      <RefundLine o={o} />
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

const RETURN_FEE = { "단순 변심": "왕복 배송비 6,000원은 환불 금액에서 차감", "불량·오배송": "배송비는 쇼핑몰 부담" } as const;
const COUPON_CHOICES = [
  { name: "사과 쿠폰 3,000원", note: "3,000원 할인 · 2만원 이상", adminOnly: false },
  { name: "무료배송 쿠폰", note: "배송비 무료", adminOnly: false },
  { name: "사과 쿠폰 5,000원", note: "5,000원 할인 · 3만원 이상 · 관리자만", adminOnly: true },
];

// 바로 처리 확인창: 제목·확인 버튼 이름, 되돌리기 어려운 처리는 빨간 버튼
const ACTION_CONFIRM: Record<QuickAction, { title: string; label: string; danger?: boolean }> = {
  address: { title: "배송지 변경", label: "배송지 변경" },
  option: { title: "옵션 변경", label: "옵션 변경" },
  partial_cancel: { title: "부분 취소", label: "취소하기", danger: true },
  duplicate_cancel: { title: "중복 승인 취소", label: "승인 취소", danger: true },
  points: { title: "보상 적립금 지급", label: "지급" },
  coupon: { title: "사과 쿠폰 발급", label: "발급" },
  return: { title: "반품 회수 접수", label: "접수" },
};

/** 바로 처리 공통: 버튼을 누르면 아래에 작은 입력칸이 열리고 [실행] → 서버가 조건을 다시 확인해 처리 */
function useQuickAction(inquiryId: number, onDone: (msg: string) => void) {
  const [open, setOpen] = useState<QuickAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function exec(action: QuickAction, body: Record<string, string | number> = {}, confirmText?: string) {
    const c = ACTION_CONFIRM[action];
    if (confirmText && !(await confirmDialog({ title: c.title, message: confirmText, confirmLabel: c.label, tone: c.danger ? "danger" : "primary" }))) return;
    setError("");
    setBusy(true);
    try {
      const r = await inquiryApi.action(inquiryId, action, body);
      setOpen(null);
      onDone(`${r.message} · [AI 초안 다시 만들기]를 누르면 처리 결과가 답변에 반영돼요.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  const toggle = (a: QuickAction) => { setError(""); setOpen(open === a ? null : a); };
  return { open, busy, error, exec, toggle };
}

function ActionButton({ label, active, tone = "plain", onClick }: { label: string; active: boolean; tone?: "plain" | "danger"; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-expanded={active}
      className={cx("rounded-lg border px-2.5 py-1 text-sm font-medium transition",
        active ? "border-primary bg-primary-soft text-primary"
          : tone === "danger" ? "border-rose-300 bg-rose-50 text-rose-700 hover:border-rose-400" : "border-hairline bg-white text-body hover:border-primary hover:text-primary")}>
      {label}
    </button>
  );
}

/** 주문 바로 처리: 지금 주문 상태에서 할 수 있는 것만 버튼으로 (배송지·옵션 변경·부분 취소 = 출고 전, 중복 승인 취소, 반품 회수 접수) */
function OrderActions({ o, inquiryId, onDone }: { o: OrderCard; inquiryId: number; onDone: (msg: string) => void }) {
  const q = useQuickAction(inquiryId, onDone);
  const beforeShipping = o.order_status === "결제 완료" || o.order_status === "상품 준비 중";
  const qty = o.quantity ?? 1;
  const choices = o.option_choices ?? [];
  const canReturn = o.order_status === "배송 완료" && !o.return_requested_at && !!o.defect_return_until && new Date(o.defect_return_until).getTime() > Date.now();
  const [address, setAddress] = useState(o.shipping_address ?? "");
  const [option, setOption] = useState("");
  const [count, setCount] = useState(1);
  const [reason, setReason] = useState<keyof typeof RETURN_FEE>(o.returnable ? "단순 변심" : "불량·오배송");
  if (!beforeShipping && !o.duplicate_payment && !canReturn) return null;
  return (
    <div className="mt-3 rounded-xl border border-primary/20 bg-primary-soft/40 p-3">
      <p className="mb-2 text-sm font-semibold text-ink">바로 처리 <span className="font-normal text-muted">· 지금 주문 상태에서 할 수 있는 것</span></p>
      <div className="flex flex-wrap gap-1.5">
        {o.duplicate_payment && <ActionButton label="중복 승인 1건 취소" tone="danger" active={q.open === "duplicate_cancel"} onClick={() => q.toggle("duplicate_cancel")} />}
        {beforeShipping && <ActionButton label="배송지 변경" active={q.open === "address"} onClick={() => q.toggle("address")} />}
        {beforeShipping && choices.length > 0 && <ActionButton label="옵션 변경" active={q.open === "option"} onClick={() => q.toggle("option")} />}
        {beforeShipping && qty > 1 && <ActionButton label="부분 취소" active={q.open === "partial_cancel"} onClick={() => q.toggle("partial_cancel")} />}
        {canReturn && <ActionButton label="반품 회수 접수" active={q.open === "return"} onClick={() => q.toggle("return")} />}
      </div>
      {q.open && (
        <div className="mt-2.5 space-y-2 rounded-lg bg-white p-2.5 text-sm">
          {q.open === "duplicate_cancel" && (
            <>
              <p>같은 금액으로 두 번 승인된 것 중 <b>뒤 승인 1건</b>을 취소합니다. 카드사에 따라 3~5영업일 안에 반영돼요.</p>
              <Button className="min-h-9 px-4 py-1" disabled={q.busy} onClick={() => q.exec("duplicate_cancel", {}, "중복 승인 1건을 취소할까요?")}>{q.busy ? <Spinner /> : "중복 승인 취소"}</Button>
            </>
          )}
          {q.open === "address" && (
            <>
              <p className="text-xs text-muted">지금 배송지: {o.shipping_address ?? "정보 없음"}</p>
              <Input value={address} onChange={(e) => setAddress(e.target.value)} maxLength={200} aria-label="새 배송지" />
              <Button className="min-h-9 px-4 py-1" disabled={q.busy || address.trim().length < 5 || address.trim() === o.shipping_address}
                onClick={() => q.exec("address", { address: address.trim() }, `배송지를 '${address.trim()}'(으)로 바꿀까요?`)}>{q.busy ? <Spinner /> : "배송지 변경"}</Button>
            </>
          )}
          {q.open === "option" && (
            <>
              <Select value={option} onChange={(e) => setOption(e.target.value)} aria-label="새 옵션" className="w-full">
                <option value="">바꿀 옵션 고르기</option>
                {choices.map((c) => (
                  <option key={c.option} value={c.option} disabled={c.current || c.stock < qty}>
                    {c.option} · {c.current ? "지금 옵션" : stockText(c)}{!c.current && !c.sold_out && c.stock < qty ? ` (주문 수량 ${qty}개보다 적음)` : ""}
                  </option>
                ))}
              </Select>
              <Button className="min-h-9 px-4 py-1" disabled={q.busy || !option}
                onClick={() => q.exec("option", { option }, `옵션을 '${option}'(으)로 바꿀까요? 가격은 같고, 재고가 ${qty}개 옮겨져요.`)}>{q.busy ? <Spinner /> : "옵션 변경"}</Button>
            </>
          )}
          {q.open === "partial_cancel" && (
            <>
              <p>{qty}개 중 몇 개를 취소할까요? 취소한 만큼 결제가 부분 취소되고, 열린 취소 티켓은 처리 완료돼요.</p>
              <div className="flex items-center gap-2">
                <Select value={String(count)} onChange={(e) => setCount(Number(e.target.value))} aria-label="취소할 수량">
                  {Array.from({ length: qty - 1 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}개 ({won(((o.unit_price ?? 0) * n) || null)})</option>)}
                </Select>
                <Button className="min-h-9 px-4 py-1" disabled={q.busy}
                  onClick={() => q.exec("partial_cancel", { count }, `${qty}개 중 ${count}개를 취소할까요?`)}>{q.busy ? <Spinner /> : `${count}개 취소`}</Button>
              </div>
            </>
          )}
          {q.open === "return" && (
            <>
              <Select value={reason} onChange={(e) => setReason(e.target.value as keyof typeof RETURN_FEE)} aria-label="반품 사유" className="w-full">
                <option value="단순 변심" disabled={!o.returnable}>단순 변심{o.returnable ? "" : " (7일 지남)"}</option>
                <option value="불량·오배송">불량·오배송</option>
              </Select>
              <p className="text-xs text-muted">1~3영업일 안에 택배 기사 방문 · {RETURN_FEE[reason]}</p>
              <Button className="min-h-9 px-4 py-1" disabled={q.busy}
                onClick={() => q.exec("return", { reason }, `${reason} 반품 회수를 접수할까요?`)}>{q.busy ? <Spinner /> : "회수 접수"}</Button>
            </>
          )}
          {q.error && <Alert>{q.error}</Alert>}
        </div>
      )}
    </div>
  );
}

/** 고객 바로 처리: 보상 적립금(상담원 3,000원까지), 사과 쿠폰 */
function CustomerActions({ inquiryId, isAdmin, onDone }: { inquiryId: number; isAdmin: boolean; onDone: (msg: string) => void }) {
  const q = useQuickAction(inquiryId, onDone);
  const limit = isAdmin ? 50000 : 3000;
  const [amount, setAmount] = useState(1000);
  const [reason, setReason] = useState("");
  const [coupon, setCoupon] = useState(COUPON_CHOICES[0].name);
  return (
    <div className="mt-3 border-t border-hairline pt-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-sm font-semibold text-body">보상</span>
        <ActionButton label="적립금 지급" active={q.open === "points"} onClick={() => q.toggle("points")} />
        <ActionButton label="쿠폰 발급" active={q.open === "coupon"} onClick={() => q.toggle("coupon")} />
      </div>
      {q.open === "points" && (
        <div className="mt-2 space-y-2 rounded-lg bg-surface-soft p-2.5 text-sm">
          <div className="flex items-center gap-2">
            <Input type="number" min={100} max={limit} step={100} value={amount} onChange={(e) => setAmount(Number(e.target.value))}
              className="min-h-9! w-28! flex-none" aria-label="적립금" />
            <span className="text-xs text-muted">원 · 1회 {limit.toLocaleString()}원까지{isAdmin ? "" : " (더 큰 금액은 관리자)"}</span>
          </div>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={50} placeholder="사유 (예: 배송 지연 사과, 만료 적립금 복구)" aria-label="사유" />
          <Button className="min-h-9 px-4 py-1" disabled={q.busy || amount < 100 || amount > limit}
            onClick={() => q.exec("points", { amount, reason: reason.trim() || "상담 보상" }, `적립금 ${amount.toLocaleString()}원을 지급할까요?`)}>{q.busy ? <Spinner /> : "지급"}</Button>
        </div>
      )}
      {q.open === "coupon" && (
        <div className="mt-2 space-y-2 rounded-lg bg-surface-soft p-2.5 text-sm">
          <Select value={coupon} onChange={(e) => setCoupon(e.target.value)} aria-label="쿠폰" className="w-full">
            {COUPON_CHOICES.map((c) => <option key={c.name} value={c.name} disabled={c.adminOnly && !isAdmin}>{c.name} · {c.note}</option>)}
          </Select>
          <Button className="min-h-9 px-4 py-1" disabled={q.busy}
            onClick={() => q.exec("coupon", { coupon }, `'${coupon}'을(를) 발급할까요? (30일)`)}>{q.busy ? <Spinner /> : "발급"}</Button>
        </div>
      )}
      {q.error && <div className="mt-2"><Alert>{q.error}</Alert></div>}
    </div>
  );
}

/** 접는 소제목 (결제·환불 내역, 배송 추적 등) */
function SubFold({ title, open, children }: { title: string; open?: boolean; children: ReactNode }) {
  return (
    <details className="group/sub mt-3 border-t border-hairline pt-2.5" open={open}>
      <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold text-body hover:text-primary">
        {title}
        <span className="font-normal text-muted"><span className="group-open/sub:hidden">펼치기 ▾</span><span className="hidden group-open/sub:inline">접기 ▴</span></span>
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

/** 재고 한 줄: '재고 8개' / '재고 2개 (적음)' / '품절 · 재입고 11/26' */
function stockText(c: NonNullable<OrderCard["option_choices"]>[number]) {
  if (c.sold_out) {
    if (!c.restock_at) return "품절 · 재입고 미정";
    const d = new Date(c.restock_at);
    return `품절 · 재입고 ${d.getMonth() + 1}/${d.getDate()} 예정`;
  }
  return `재고 ${c.stock}개${c.low ? " (적음)" : ""}`;
}

/** 같은 상품의 옵션별 재고 (교환·옵션 변경 문의에 바로 안내할 수 있게) */
function StockList({ o }: { o: OrderCard }) {
  return (
    <ul className="space-y-1 text-sm">
      {(o.option_choices ?? []).map((c) => (
        <li key={c.option} className="flex items-center justify-between gap-2">
          <span className={cx(c.current && "font-semibold text-ink")}>{c.option}{c.current && <span className="ml-1 text-xs font-normal text-muted">(주문한 옵션)</span>}</span>
          <span className={cx("shrink-0 text-xs", c.sold_out ? "font-semibold text-rose-700" : c.low ? "font-semibold text-amber-700" : "text-muted")}>{stockText(c)}</span>
        </li>
      ))}
    </ul>
  );
}

/** 결제·취소·환불 내역 (중복 승인 확인용: 승인 번호·시각까지) */
function PaymentList({ o }: { o: OrderCard }) {
  const rows = o.payments ?? [];
  return (
    <ul className="space-y-1.5 text-sm">
      {rows.map((p, i) => (
        <li key={i} className="flex flex-wrap items-baseline gap-x-2">
          <span className={cx("rounded px-1.5 py-0.5 text-xs font-semibold",
            p.kind === "승인" ? "bg-primary-soft text-primary" : "bg-slate-100 text-slate-700")}>{p.kind}{p.status === "예정" ? " 예정" : ""}</span>
          <span className="font-semibold tabular-nums text-ink">{won(p.amount)}</span>
          <span className="text-xs text-muted">{p.method ?? ""}{p.approval_no ? ` · 승인번호 ${p.approval_no}` : ""} · {formatDate(p.at)}</span>
          {p.memo && <span className="w-full text-xs text-muted">{p.memo}</span>}
        </li>
      ))}
    </ul>
  );
}

/** 배송 추적 단계 (택배사 조회 결과) */
function ShipmentList({ o }: { o: OrderCard }) {
  const steps = o.shipment_events ?? [];
  return (
    <ol className="relative space-y-2 border-l border-hairline pl-4 text-sm">
      {steps.map((e, i) => (
        <li key={i}>
          <span className={cx("absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full", i === steps.length - 1 ? "bg-primary" : "bg-slate-300")} />
          <span className={cx(i === steps.length - 1 ? "font-semibold text-ink" : "text-body")}>{e.status}</span>
          {e.location && <span className="text-muted"> · {e.location}</span>}
          <span className="block text-xs text-muted">{formatDate(e.at)}</span>
        </li>
      ))}
    </ol>
  );
}

/** 상품명(옵션) + 주문번호·금액·수량 (주문 정보의 머리글) */
function OrderHead({ o }: { o: OrderCard }) {
  const qty = o.quantity ?? 1;
  return (
    <div className="min-w-0">
      <p className="truncate text-base font-semibold text-ink">{o.product_name}</p>
      <p className="text-sm text-muted">
        <span className="font-mono text-body">{o.order_number}</span> · {won(o.amount)}
        {qty > 1 && <span className="font-semibold text-ink"> · {qty}개 ({won(o.unit_price ?? null)} × {qty})</span>}
      </p>
    </div>
  );
}

const CLOSE_REASONS = ["중복 문의", "스팸·광고", "고객 철회", "전화로 안내", "기타"] as const;

/** 답변 없이 완료: 사유를 고름 (고객 화면에 '종료됨'과 사유에 맞는 안내가 보임, 처리 이력에도 남음) */
function CloseDialog({ onClose, onDone }: { onClose: () => void; onDone: (reason: string) => void }) {
  const [reason, setReason] = useState<string>("");
  return (
    <Modal title="답변 없이 완료 처리" onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>취소</Button>
        <Button disabled={!reason} onClick={() => onDone(reason)}>완료 처리</Button>
      </>}>
      <p>고객에게 답변을 보내지 않고 끝내는 이유를 골라 주세요. 고객 화면에는 '종료됨'으로 보여요.</p>
      <div className="grid grid-cols-2 gap-2">
        {CLOSE_REASONS.map((r) => (
          <label key={r} className={cx("flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2",
            reason === r ? "border-primary bg-primary-soft" : "border-hairline hover:bg-surface-soft")}>
            <input type="radio" name="close-reason" checked={reason === r} onChange={() => setReason(r)} />{r}
          </label>
        ))}
      </div>
    </Modal>
  );
}

/** 넘기기: 다른 상담원에게 인계 (인계 메모 필수 → 공유 메모로 남고, 받는 사람에게 🔔 배정 알림) */
function HandoverDialog({ staff, meId, onClose, onDone }: {
  staff: User[]; meId: number; onClose: () => void; onDone: (to: number, memo: string) => void;
}) {
  const [to, setTo] = useState("");
  const [memo, setMemo] = useState("");
  const others = staff.filter((u) => u.id !== meId);
  return (
    <Modal title="다른 상담원에게 넘기기" onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>취소</Button>
        <Button disabled={!to || memo.trim().length < 2} onClick={() => onDone(Number(to), memo.trim())}>넘기기</Button>
      </>}>
      <label className="block space-y-1">
        <span className="font-semibold text-ink">받는 사람</span>
        <Select value={to} onChange={(e) => setTo(e.target.value)} className="w-full" aria-label="받는 사람">
          <option value="">고르기</option>
          {others.map((u) => <option key={u.id} value={u.id}>{u.display_name}</option>)}
        </Select>
      </label>
      <label className="block space-y-1">
        <span className="font-semibold text-ink">인계 메모 (필수)</span>
        <textarea value={memo} onChange={(e) => setMemo(e.target.value)} maxLength={500} aria-label="인계 메모"
          className="min-h-24 w-full rounded-xl border border-hairline bg-white px-3 py-2 outline-none focus:border-primary"
          placeholder="지금까지 한 일과 남은 일 (예: 택배사 분실 조사 요청함, 회신 오면 재발송 안내)" />
      </label>
      <p className="text-xs text-muted">메모는 상담원 공유 메모에 '[인계]'로 남아요. 넘긴 뒤에는 이 문의를 볼 수 없어요.</p>
    </Modal>
  );
}

/** 주문번호 입력·변경: 고객이 빠뜨렸거나 잘못 적은 번호를 상담원이 확인한 번호로 (추가 문의·전화로 받은 번호, 고객 글에 적힌 번호) */
function OrderNumberFix({ inquiryId, current, hints, onDone, compact }: {
  inquiryId: number; current: string | null; hints: NonNullable<InquiryDetail["order_hints"]>; onDone: (msg: string) => void; compact?: boolean;
}) {
  const [open, setOpen] = useState(!compact);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function apply(number: string) {
    const ok = await confirmDialog({
      title: current ? "주문번호 변경" : "주문번호 지정",
      message: `이 문의의 주문번호를 ${current ? `${current} → ` : ""}${number}(으)로 ${current ? "바꿀까요" : "지정할까요"}?\n주문 정보가 이 번호로 다시 확인되고, 처리 이력에 남아요.`,
      confirmLabel: current ? "변경" : "지정",
    });
    if (!ok) return;
    setError("");
    setBusy(true);
    try {
      await inquiryApi.setOrderNumber(inquiryId, number);
      setValue("");
      onDone(`주문번호를 ${number}(으)로 ${current ? "바꿨어요" : "지정했어요"}. 주문 정보를 다시 확인했어요.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-3 space-y-2">
      {hints.map((h) => (
        <div key={h.order_number} className="flex flex-wrap items-center gap-2 rounded-xl border border-primary/30 bg-primary-soft/50 px-3 py-2 text-sm">
          <span className="min-w-0 flex-1">
            고객이 적은 주문번호 <b className="font-mono text-ink">{h.order_number}</b>
            <span className="block text-xs text-muted">
              {h.found ? `${h.product_name ?? "주문"} · ${h.email_match ? "본인 주문" : "주문자 이메일이 달라요 (본인 확인 필요)"}` : "이 번호의 주문이 없어요"}
            </span>
          </span>
          {h.found && <Button className="min-h-9 px-3 py-1" disabled={busy} onClick={() => apply(h.order_number)}>이 번호로 확인</Button>}
        </div>
      ))}
      {open ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="20261103-0042" aria-label="주문번호 입력"
            inputMode="numeric" maxLength={30} className="min-h-9! w-44! flex-none py-1.5 font-mono" disabled={busy}
            onKeyDown={(e) => { if (e.key === "Enter" && value.trim()) apply(value.replace(/\s/g, "")); }} />
          <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={busy || !value.trim()} onClick={() => apply(value.replace(/\s/g, ""))}>
            {busy ? <Spinner /> : current ? "주문번호 변경" : "주문번호 지정"}
          </Button>
          <span className="text-xs text-muted">고객에게 받은 번호를 넣으면 주문을 다시 확인해요</span>
        </div>
      ) : (
        <button type="button" onClick={() => setOpen(true)} className="text-xs font-semibold text-primary hover:underline">주문번호 변경</button>
      )}
      {error && <Alert>{error}</Alert>}
    </div>
  );
}

/** 주문 정보: 고객이 적은 주문(크게) + 문의 이메일로 찾은 다른 주문(핵심만 보이고 누르면 상세).
 *  category: 결제 문의면 결제·환불 내역, 배송 문의면 배송 추적을 펼쳐 둠. 주문이 필요한 유형인데 주문번호가 없으면 요청 버튼 */
function OrderInfo({ o, others, hints, category, needsOrder, inquiryId, onDone }: {
  o: OrderCard | null; others: OrderCard[]; hints: NonNullable<InquiryDetail["order_hints"]>; category: string | null; needsOrder: boolean;
  inquiryId: number; onDone: (msg: string) => void;
}) {
  const { user } = useAuth();
  const canOpen = (assignedTo: number | null | undefined) => user?.role === "admin" || assignedTo === user?.id;   // 상담원은 맡은 문의만
  const [assignError, setAssignError] = useState("");
  // 주문을 확인하지 못한 문의(번호 없음·없는 주문·다른 사람 주문)는 주문번호 입력칸을 펼쳐 두고, 확인된 주문은 [주문번호 변경]만
  const unresolved = !o || !o.found || o.email_match === false;
  const showFix = unresolved ? (needsOrder || !!o || hints.length > 0 || others.length > 0) : true;
  const assign = async (number: string) => {
    if (!(await confirmDialog({ title: "이 주문으로 지정", confirmLabel: "지정",
      message: `이메일로 찾은 주문 ${number}을(를) 이 문의의 주문으로 지정할까요?\n어떤 주문인지 고객에게 확인한 뒤 지정하세요.` }))) return;
    setAssignError("");
    try {
      await inquiryApi.setOrderNumber(inquiryId, number);
      onDone(`주문번호를 ${number}(으)로 지정했어요. 주문 정보를 다시 확인했어요.`);
    } catch (err) {
      setAssignError(errorMessage(err));   // 실패는 빨간 안내로 (성공 안내에 섞이지 않게)
    }
  };
  const payments = o?.payments ?? [];
  const steps = o?.shipment_events ?? [];
  const related = o?.related_inquiries ?? [];
  return (
    <Card title="주문 정보">
      {needsOrder && (
        <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
          <p className="font-semibold">{category} 문의인데 {o ? "주문번호를 찾을 수 없어요" : "주문번호가 없어요"}</p>
          <p className="mt-0.5 text-xs">주문을 확인해야 정확히 안내할 수 있어요.{others.length > 0 && " 아래 이메일로 찾은 주문 중 어느 것인지 고객에게 확인하세요."}</p>
          <button type="button" onClick={() => insertIntoReply(ORDER_NUMBER_ASK)}
            className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm font-semibold text-amber-900 hover:bg-amber-100">
            + 주문번호 요청 문구 넣기
          </button>
        </div>
      )}
      {!o && !needsOrder && <p className="text-sm text-muted">주문번호 없이 남긴 문의입니다{category ? ` (${category} 문의라 주문 확인이 꼭 필요하지는 않음)` : ""}.</p>}
      {o && !o.found && (
        <div className="mb-3"><Alert>주문번호 <b className="font-mono">{o.order_number}</b>를 찾을 수 없습니다. 고객에게 주문번호를 다시 확인해 주세요.</Alert></div>
      )}
      {assignError && <div className="mb-3"><Alert>{assignError}</Alert></div>}
      {showFix && unresolved && <OrderNumberFix inquiryId={inquiryId} current={o?.order_number ?? null} hints={hints} onDone={onDone} />}
      {o?.found && (
        <>
          {o.email_match === false && (
            <div className="mb-3"><Alert>문의 이메일과 주문자 이메일이 다릅니다 (주문자: {o.orderer}). 본인 확인 전에는 주문 정보를 안내하지 마세요.</Alert></div>
          )}
          {o.duplicate_payment && (
            <div className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
              ⚠ 같은 금액이 10분 안에 두 번 승인됐어요 (중복 결제 의심). 아래 결제·환불 내역에서 승인번호를 확인하세요.
            </div>
          )}
          {related.length > 0 && (
            <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <p className="font-semibold">이 주문의 다른 문의 {related.length}건 · 같은 내용을 서로 다르게 안내하지 않게 확인하세요</p>
              <ul className="mt-1 space-y-0.5">
                {related.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-2">
                    {canOpen(r.assigned_to)
                      ? <Link to={`/admin/inquiries/${r.id}`} className="truncate text-primary hover:underline">{r.title}</Link>
                      : <span className="truncate" title="다른 상담원이 맡은 문의예요">{r.title} <span className="text-xs text-muted">(다른 상담원 담당)</span></span>}
                    <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted"><Badge value={r.status} />{timeAgo(r.created_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="mb-3">
            <p className="mb-0.5 text-xs font-semibold text-emerald-700">고객이 문의한 주문</p>
            <OrderHead o={o} />
            {o.option && <p className="text-xs text-muted">옵션: {o.option}</p>}
          </div>
          <OrderRows o={o} />
          {o.shipping_address && <p className="mt-1.5 text-sm"><span className="text-muted">배송지 </span>{o.shipping_address}</p>}
          {o.email_match !== false && <OrderActions key={`${o.order_number}-${o.order_status}-${o.quantity}-${o.product_name}-${payments.length}`} o={o} inquiryId={inquiryId} onDone={onDone} />}
          {payments.length > 0 && (
            <SubFold title={`결제·환불 내역 (${payments.length})`}
              open={o.duplicate_payment || category === "결제" || category === "반품·환불" || payments.some((p) => p.kind !== "승인")}>
              <PaymentList o={o} />
            </SubFold>
          )}
          {steps.length > 0 && (
            <SubFold title={`배송 추적 (${steps.length}단계${o.carrier ? ` · ${o.carrier}` : ""})`} open={category === "배송"}>
              <ShipmentList o={o} />
            </SubFold>
          )}
          {(o.option_choices?.length ?? 0) > 0 && (
            <SubFold title={`옵션별 재고 (${o.option_choices!.length})`} open={category === "교환" || category === "상품"}>
              <StockList o={o} />
            </SubFold>
          )}
        </>
      )}

      {others.length > 0 ? (
        <details className={cx("group/others", o?.found && "mt-4 border-t border-hairline pt-3")} open={needsOrder}>
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
                    {(x.payments?.length ?? 0) > 0 && <SubFold title={`결제·환불 내역 (${x.payments!.length})`}><PaymentList o={x} /></SubFold>}
                    {unresolved && (
                      <Button variant="ghost" className="mt-2 min-h-9 px-3 py-1" onClick={() => assign(x.order_number)}>이 주문으로 지정</Button>
                    )}
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </details>
      ) : !o?.found && (
        <p className="mt-1 text-sm text-muted">이 이메일로 된 주문도 없습니다.</p>
      )}
      {!unresolved && o && (
        <div className="mt-3 border-t border-hairline pt-2.5">
          <OrderNumberFix inquiryId={inquiryId} current={o.order_number} hints={hints} onDone={onDone} compact />
        </div>
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
                  {t.ticket_type === "취소" && o?.found && !cancelBlocked && (o.quantity ?? 1) > 1 && (
                    <p className="rounded-lg bg-amber-50 px-2.5 py-1.5 text-sm text-amber-900">
                      ⚠ {o.quantity}개 주문이에요. 승인하면 <b>주문 전체</b>가 취소됩니다. 일부만 취소하려면 아래 주문 정보의 <b>[부분 취소]</b>를 쓰세요 (이 티켓도 함께 처리돼요).
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
        <Row label="AI 처리 작업">
          <span title={log.selected_tool ? TOOL_LABEL[log.selected_tool]?.help : undefined}>{toolLabel(log.selected_tool)}</span>{" "}
          <span className="text-muted">({byLabel(log.decided_by)})</span>{" "}
          {log.tool_success === false && <span className="text-rose-700">· 미완료: {failReason(log.tool_output)}</span>}
        </Row>
        <Row label="검색된 FAQ">
          {log.retrieved_faqs.length ? (
            <ul className="space-y-0.5">
              {log.retrieved_faqs.map(([code, s]) => (
                <li key={code} className="text-sm"><span className="font-mono">{code}</span> {faqTitles[code] ?? ""} <span className="text-slate-500">유사도 {s.toFixed(2)}</span></li>
              ))}
            </ul>
          ) : "-"}
        </Row>
        <Row label="AI 모델">{log.llm_model ?? "사용 안 함 (규칙으로 바로)"}</Row>
        <Row label="AI 사용량">{log.tokens?.calls ? `입력 ${log.tokens.input} · 출력 ${log.tokens.output} (${log.tokens.calls}회)` : "-"}</Row>
        <Row label="처리 시간">{log.latency_ms !== null ? `${(log.latency_ms / 1000).toFixed(1)}초` : "-"}</Row>
        {log.error && <Row label="오류"><span className="break-all text-rose-700">{log.error}</span></Row>}
        <Row label="결과 원본">
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
  const [dialog, setDialog] = useState<"close" | "handover" | null>(null);
  // 쓰던 답변이 있으면 다른 문의로 옮기기 전에 물음 (옮기면 답변 칸이 비워짐)
  const dirty = useRef(false);
  async function go(to: number | null | undefined) {
    if (!to) return;
    if (dirty.current && !(await confirmDialog({
      title: "작성 중인 답변이 있어요", message: "다른 문의로 옮기면 쓰던 답변이 사라져요.\n남기려면 [초안 저장]을 먼저 눌러 주세요.",
      confirmLabel: "옮기기", cancelLabel: "머무르기", tone: "danger",
    }))) return;
    dirty.current = false;
    navigate(`/admin/inquiries/${to}`);
  }
  // 새로 고침·창 닫기도 브라우저가 한 번 물음
  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => { if (dirty.current) e.preventDefault(); };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, []);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [queue, setQueue] = useState<{ total: number; position: number | null; prev_id: number | null; next_id: number | null } | null>(null);
  const navigate = useNavigate();

  // 지금 보고 있는 문의 번호: 늦게 도착한 다른 문의의 응답(예: 발송 5초 뒤 다시 불러오기)이 화면을 덮지 않게
  const currentId = useRef(id);
  currentId.current = id;
  const load = useCallback(() => {
    inquiryApi.get(id)
      .then((d) => { if (currentId.current === id) setData(d); })
      .catch((err) => { if (currentId.current === id) setError(errorMessage(err)); });
  }, [id]);
  useEffect(load, [load]);
  // 다른 문의로 옮기면 안내 문구를 지움
  useEffect(() => { setNotice(""); setActionError(""); }, [id]);
  // 단축키 Alt+← / Alt+→ : 이전·다음 미처리 문의
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || !queue) return;
      const to = e.key === "ArrowLeft" ? queue.prev_id : e.key === "ArrowRight" ? queue.next_id : null;
      if (to) { e.preventDefault(); go(to); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queue, navigate]);
  // 처리 대기열 위치: 상태가 바뀔 때마다 다시 (완료하면 대기열에서 빠지고 '다음 미처리'가 바뀜)
  useEffect(() => {
    inquiryApi.queue(id).then(setQueue).catch(() => setQueue(null));
  }, [id, data?.status]);
  useEffect(() => {
    inquiryApi.staff().then(setStaff).catch(() => setStaff([]));   // 관리자: 배정, 상담원: 넘길 상대
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
  const actionDone = (m: string) => { setNotice(m); load(); };   // 바로 처리 결과 → 위쪽 안내 + 다시 불러오기
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
        {p?.points_balance != null && (
          <Row label="적립금">
            <span className="font-semibold">{p.points_balance.toLocaleString()}원</span>
            {p.points_pending > 0 && <span className="text-muted"> · 적립 예정 {p.points_pending.toLocaleString()}원</span>}
            {p.coupons.length > 0 && <span className="text-muted"> · 쿠폰 {p.coupons.filter((c) => c.state === "사용 가능").length}장</span>}
          </Row>
        )}
      </dl>
      {p && (p.point_history.length > 0 || p.coupons.length > 0) && (
        <SubFold title="적립금·쿠폰 내역" open={a?.category === "쿠폰·적립금·회원"}>
          {p.point_history.length > 0 && (
            <ul className="space-y-1 text-sm">
              {p.point_history.map((h, i) => (
                <li key={i} className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate">{h.reason}{h.status === "예정" && <span className="text-amber-700"> (예정)</span>}
                    <span className="text-xs text-muted"> · {formatDate(h.at)}</span></span>
                  <span className={cx("shrink-0 font-semibold tabular-nums", h.amount < 0 ? "text-rose-700" : "text-emerald-700")}>
                    {h.amount > 0 ? "+" : ""}{h.amount.toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {p.coupons.length > 0 && (
            <ul className="mt-2.5 space-y-1 border-t border-hairline pt-2 text-sm">
              {p.coupons.map((c, i) => (
                <li key={i} className={cx("flex items-baseline justify-between gap-2", c.state !== "사용 가능" && "text-muted")}>
                  <span className="min-w-0 truncate">{c.name} <span className="text-xs">· {c.benefit}{c.min_amount ? ` · ${c.min_amount.toLocaleString()}원 이상` : ""}</span></span>
                  <span className={cx("shrink-0 text-xs", c.state === "사용 가능" && "font-semibold text-primary")}>
                    {c.state}{c.state === "사용 가능" && ` · ~${formatDate(c.expires_at).split(" ").slice(0, 3).join(" ")}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </SubFold>
      )}
      {warn && (
        <p className="mt-2 rounded-lg bg-amber-50 px-3 py-1.5 text-sm text-amber-900">
          ⚠ 응대에 신경 쓸 고객:
          {p!.negative_ratings > 0 && <> 이전 답변에 👎 {p!.negative_ratings}번</>}
          {p!.negative_ratings > 0 && p!.negative_inquiries >= 2 && " ·"}
          {p!.negative_inquiries >= 2 && <> 불만 문의 {p!.negative_inquiries}건</>}
        </p>
      )}
      {p?.points_balance != null && <CustomerActions inquiryId={data.id} isAdmin={user?.role === "admin"} onDone={actionDone} />}
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
  // 주문을 확인해야 하는 문의인데 주문을 못 찾음: 주문 관련 유형 + 사람이 처리 (FAQ로 자동 답변한 일반 질문은 제외)
  const needsOrder = !!a && ORDER_CATEGORIES.includes(a.category) && a.decision !== "자동 답변" && !data.order?.found;
  const orderCard = <OrderInfo o={data.order} others={data.email_orders} hints={data.order_hints ?? []} category={a?.category ?? null} needsOrder={needsOrder}
    inquiryId={data.id} onDone={actionDone} />;
  // 주문 관련 문의(주문번호를 적었거나 이메일로 찾은 주문이 있음)는 주문 정보가 판단의 핵심 → 위에. 아니면 고객을 위에
  const orderFirst = !!data.order || needsOrder;

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
                  onClick={() => go(queue.prev_id)}>◀</Button>
                <span className="px-1 tabular-nums text-muted" title="미처리 대기열 (긴급도 → 오래된 순)">
                  {queue.position ? `${queue.position} / ${queue.total}` : `대기 ${queue.total}건`}
                </span>
                <Button variant="ghost" className="min-h-9 px-2.5 py-1" disabled={!queue.next_id} title="다음 미처리 문의 (Alt+→)"
                  onClick={() => go(queue.next_id)}>▶</Button>
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
              <>
                <span className="font-medium text-ink">{data.assigned_to?.display_name ?? "미배정"}</span>
                {!data.assigned_to && (
                  <Button disabled={busy} onClick={() => run(() => inquiryApi.assign(id, user!.id))}>내가 맡기</Button>
                )}
                {data.assigned_to?.id === user?.id && (
                  <Button variant="ghost" disabled={busy} onClick={() => setDialog("handover")}>넘기기</Button>
                )}
              </>
            )}
            {isOpen ? (
              <Button disabled={busy || (user?.role !== "admin" && data.assigned_to?.id !== user?.id)}
                onClick={() => (data.responses.some((r) => r.status === "발송") && !data.messages.length
                  ? run(() => inquiryApi.setStatus(id, "완료")) : setDialog("close"))}>완료 처리</Button>
            ) : (
              <Button variant="ghost" disabled={busy} onClick={() => run(() => inquiryApi.setStatus(id, "담당자 처리"))}>다시 열기</Button>
            )}
          </div>
        </div>
        {actionError && <div className="mt-2"><Alert>{actionError}</Alert></div>}
        {user?.role !== "admin" && !data.assigned_to && (
          <div className="mt-2"><Alert kind="info">아직 담당자가 없는 문의예요. [내가 맡기]를 누르면 답변·처리할 수 있어요.</Alert></div>
        )}
        {dialog === "close" && (
          <CloseDialog onClose={() => setDialog(null)}
            onDone={(reason) => { setDialog(null); run(() => inquiryApi.setStatus(id, "완료", reason)); }} />
        )}
        {dialog === "handover" && user && (
          <HandoverDialog staff={staff} meId={user.id} onClose={() => setDialog(null)}
            onDone={(to, memo) => {
              setDialog(null);
              run(async () => { await inquiryApi.assign(id, to, memo); navigate("/admin/inquiries?open=true"); });
            }} />
        )}
        {notice && <div className="mt-2"><Alert kind="success">{notice}</Alert></div>}
        {/* 처리가 끝난 문의: 다음 미처리 문의로 바로 (목록으로 돌아갔다 오지 않게) */}
        {!isOpen && queue?.next_id && (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
            <span>
              {data.recheck ? `답변은 보냈어요 (확인 후 다시 안내 ${formatDate(data.recheck.due_at)}까지).` : "이 문의는 처리됐어요."} 미처리 {queue.total}건이 남아 있습니다.
            </span>
            <Button className="min-h-9 px-4 py-1" onClick={() => go(queue.next_id)}>다음 미처리 문의 →</Button>
          </div>
        )}
      </div>

      <DecisionBanner d={data} />

      {/* 왼쪽(일하는 곳)이 넓게: 오른쪽 참고 정보는 고정 폭 (lg 22rem, xl 25rem) */}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_25rem]">
        {/* 왼쪽: 일하는 곳 */}
        <div className="space-y-4">
          <Card title="문의와 답변">
            {/* key: 다른 문의로 옮기면 쓰던 답변·다시 안내 체크·요청을 모두 비움 (A 문의에 쓴 글이 B 고객에게 가지 않게) */}
            <AnswerComposer key={data.id} data={data} refFaqCodes={refFaqs.map(([code]) => code)} onChanged={load}
              onDirtyChange={(d) => { dirty.current = d; }} />
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
          {/* 상담원 공유 메모: 상담원끼리 공유 (고객 대화와 따로, 답변을 쓰는 동안에도 보이게 맨 위) */}
          <InternalNotes key={data.id} data={data} onChanged={load} />
          {/* 처리할 티켓이 있으면 그 아래 (상담원이 가장 먼저 할 일) */}
          {pendingTickets && <Tickets data={data} onChanged={(m) => { setNotice(m); load(); }} />}
          {orderFirst ? <>{orderCard}{customerCard}</> : <>{customerCard}{orderCard}</>}

          {/* 요약 줄(유형·확신도·감정·긴급도)만으로 충분해 접어 둠. 확신도가 낮으면 유형을 확인해야 하니 펼침 */}
          <Fold id="analysis" title="AI 분석" defaultOpen={lowConf} summary={a ? `${a.category} (AI 확신 ${(a.confidence * 100).toFixed(0)}%)${lowConf ? " ⚠ 유형 판단 불확실" : ""} · ${a.sentiment} · 긴급도 ${a.urgency}` : "분석 전"}>
            {!a ? <p className="text-sm text-muted">분석 전</p> : (
              <>
                <dl className="grid grid-cols-[3.5rem_1fr] items-center gap-x-3 gap-y-1.5 text-sm">
                  <Row label="유형">
                    <span className="font-semibold">{a.category}</span>{" "}
                    <span className={cx(lowConf ? "font-semibold text-rose-700" : "text-muted")}>
                      AI 확신 {(a.confidence * 100).toFixed(0)}%{lowConf && " · 유형 판단 불확실, 유형이 맞는지 확인해 주세요"}
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
