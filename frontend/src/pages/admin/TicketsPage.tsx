// 취소·교환·반품 (/admin/tickets): AI가 접수한 취소·교환·환불(반품) 요청을 한곳에서 (backend/api/tickets.py)
// - 기본은 '승인 대기'(오래된 것부터). 승인·반려는 문의 상세에서 주문 정보를 보고 함 → 줄을 누르면 그 문의로
// - '환불 진행' 탭: 승인한 뒤 돈이 돌아가는 상황 (결제 내역의 환불 예정·완료, 예정일 지남은 빨강). 조회 전용
// - 상담원은 내가 맡은 문의의 요청·주문만 보임
import { Link, useNavigate, useSearchParams } from "react-router";
import { useEffect, useState } from "react";

import { Alert, Badge, Button, Select, Spinner, cx, formatDate } from "../../components/ui";
import { errorMessage, opsApi } from "../../services/api";
import { TICKET_KIND, ticketKind } from "../../services/labels";

const SIZE = 30;
const TABS = [
  { value: "접수", label: "승인 대기" },
  { value: "승인", label: "승인" },
  { value: "반려", label: "반려" },
  { value: "all", label: "전체" },
  { value: "refund", label: "환불 진행" },
];
const TYPE_STYLE: Record<string, string> = {
  취소: "bg-rose-50 text-rose-700", 교환: "bg-sky-50 text-sky-800", 환불: "bg-amber-50 text-amber-800",
};
const STATUS_STYLE: Record<string, string> = {
  접수: "bg-primary-soft text-primary", 승인: "bg-emerald-50 text-emerald-700", 반려: "bg-slate-100 text-slate-600",
};
const won = (n: number) => `${n.toLocaleString()}원`;

/** 접수 뒤 지난 시간 (승인 대기가 오래되면 주황 → 빨강) */
function waited(iso: string) {
  const hours = (Date.now() - new Date(iso).getTime()) / 3600000;
  const text = hours < 1 ? `${Math.max(1, Math.round(hours * 60))}분` : hours < 48 ? `${Math.round(hours)}시간` : `${Math.round(hours / 24)}일`;
  return { text: `${text} 대기`, tone: hours >= 24 ? "text-rose-700 font-semibold" : hours >= 4 ? "text-amber-700 font-semibold" : "text-muted" };
}

export default function TicketsPage() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "접수";
  const type = params.get("type") ?? "";
  const page = Number(params.get("page") ?? 1);
  const [data, setData] = useState<Awaited<ReturnType<typeof opsApi.tickets>> | null>(null);
  const [error, setError] = useState("");
  const [refundCount, setRefundCount] = useState<number | null>(null);
  const refundView = status === "refund";

  // '환불 진행' 탭 숫자 = 환불 예정 건수
  useEffect(() => {
    opsApi.refunds({ state: "예정" }).then((r) => setRefundCount(r.summary.pending)).catch(() => setRefundCount(null));
  }, []);

  useEffect(() => {
    if (refundView) return;
    let stale = false;   // 탭을 빨리 바꿀 때 앞 요청의 늦은 응답은 버림
    setError("");
    opsApi.tickets({ status, ticket_type: type, page })
      .then((d) => { if (!stale) setData(d); })
      .catch((err) => { if (!stale) setError(errorMessage(err)); });
    return () => { stale = true; };
  }, [status, type, page, refundView]);

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };
  const lastPage = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1;
  const pendingView = status === "접수";

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">취소·교환·반품</h1>
        <p className="mt-1 text-sm text-muted">
          AI가 문의에서 접수한 <b>취소·교환·반품 요청</b>이에요. 줄을 누르면 문의 상세로 가서 주문 정보를 보고 승인·반려해요.{" "}
          <b>취소와 반품은 둘 다 승인하면 환불</b>이 진행돼요 (취소는 바로 전액, 반품은 회수·검수 뒤 3영업일 안).
          환불이 잘 되고 있는지는 <b>환불 진행</b> 탭에서 봐요.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" className="flex rounded-xl border border-hairline bg-white p-1">
          {TABS.map((t) => {
            const count = t.value === "all" ? null : t.value === "refund" ? refundCount : data?.counts[t.value];
            return (
              <button key={t.value} type="button" role="tab" aria-selected={status === t.value}
                onClick={() => update("status", t.value === "접수" ? "" : t.value)}
                className={cx("rounded-lg px-3 py-1.5 text-sm font-semibold",
                  status === t.value ? "bg-primary text-white" : "text-body hover:bg-surface-soft")}>
                {t.label}{count != null && <span className={cx("ml-1.5", status === t.value ? "text-white/80" : "text-muted")}>{count}</span>}
              </button>
            );
          })}
        </div>
        {!refundView && (
          <Select value={type} onChange={(e) => update("type", e.target.value)} aria-label="요청 종류">
            <option value="">모든 종류</option>
            <option value="취소">취소 (전액 환불)</option>
            <option value="교환">교환</option>
            <option value="환불">반품 (회수 후 환불)</option>
          </Select>
        )}
      </div>

      {refundView ? <RefundView /> : <>
      {error && <Alert>{error}</Alert>}

      <div className="overflow-x-auto rounded-2xl border border-hairline bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-hairline text-sm text-muted">
            <tr>{["종류", "문의", "주문", "요청 내용", pendingView ? "접수" : "처리", "담당"].map((h) => (
              <th key={h} className="whitespace-nowrap px-3 py-3 font-medium">{h}</th>
            ))}</tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {data?.items.map((t) => {
              const w = waited(t.created_at);
              return (
                <tr key={t.id} className="cursor-pointer hover:bg-surface-soft" onClick={() => navigate(`/admin/inquiries/${t.inquiry.id}`)}>
                  <td className="whitespace-nowrap px-3 py-3">
                    <span className={cx("rounded-full px-2.5 py-0.5 text-xs font-semibold", TYPE_STYLE[t.ticket_type] ?? "bg-slate-100 text-slate-700")}>
                      {ticketKind(t.ticket_type)}
                    </span>
                    {!pendingView && (
                      <span className={cx("ml-1.5 rounded-full px-2 py-0.5 text-xs font-medium", STATUS_STYLE[t.status])}>{t.status}</span>
                    )}
                    {TICKET_KIND[t.ticket_type] && <span className="mt-1 block text-xs text-muted">{TICKET_KIND[t.ticket_type].refund}</span>}
                  </td>
                  <td className="max-w-[13rem] px-3 py-3">
                    <Link to={`/admin/inquiries/${t.inquiry.id}`} onClick={(e) => e.stopPropagation()}
                      className="block truncate font-semibold text-ink hover:text-primary">{t.inquiry.title}</Link>
                    <span className="text-xs text-muted"><span className="font-mono">{t.inquiry.inquiry_number}</span> · {t.inquiry.customer_name}</span>
                  </td>
                  <td className="max-w-[13rem] px-3 py-3">
                    {t.order ? (
                      <>
                        <span className="block truncate text-ink">{t.order.product_name}</span>
                        <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                          <span className="font-mono">{t.order.order_number}</span> · {won(t.order.amount)} <Badge value={t.order.order_status} />
                        </span>
                      </>
                    ) : <span className="text-xs font-semibold text-amber-700">주문번호 확인 필요</span>}
                  </td>
                  <td className="min-w-[10rem] max-w-xs px-3 py-3 text-body">
                    <span className="line-clamp-2">{t.reason}</span>
                    {t.memo && <span className="mt-0.5 block truncate text-xs text-muted">메모: {t.memo}</span>}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3">
                    {pendingView ? (
                      <span className={w.tone}>{w.text}<span className="block text-xs font-normal text-muted">{formatDate(t.created_at)}</span></span>
                    ) : (
                      <span className="text-muted">{t.handled_at ? formatDate(t.handled_at) : "-"}
                        {t.handled_by && <span className="block text-xs">{t.handled_by}</span>}</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 text-body">{t.inquiry.assigned_to ?? <span className="text-amber-700">미배정</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!data && !error && <p className="p-6 text-center text-muted"><Spinner /></p>}
        {data?.items.length === 0 && (
          <p className="p-6 text-center text-sm text-muted">{pendingView ? "승인을 기다리는 요청이 없어요." : "이 조건의 요청이 없어요."}</p>
        )}
      </div>

      {data && data.total > SIZE && (
        <div className="flex items-center justify-end gap-2 text-sm text-muted">
          <Button variant="ghost" disabled={page <= 1} onClick={() => update("page", String(page - 1))}>이전</Button>
          <span>{page} / {lastPage}</span>
          <Button variant="ghost" disabled={page >= lastPage} onClick={() => update("page", String(page + 1))}>다음</Button>
        </div>
      )}
      </>}
    </div>
  );
}

const REFUND_STATES = [
  { value: "예정", label: "환불 예정" },
  { value: "완료", label: "완료" },
  { value: "all", label: "전체" },
];
const day = (iso: string) => new Date(iso).toLocaleDateString("ko-KR", { month: "numeric", day: "numeric", weekday: "short" });

/** 환불 진행: 승인 뒤 결제 내역의 '환불'(반품)·'승인 취소'(출고 전 취소) 줄. 실제 환불은 쇼핑몰 결제 시스템이 함 */
function RefundView() {
  const navigate = useNavigate();
  const [state, setState] = useState("예정");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Awaited<ReturnType<typeof opsApi.refunds>> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stale = false;
    setError("");
    opsApi.refunds({ state, page })
      .then((d) => { if (!stale) setData(d); })
      .catch((err) => { if (!stale) setError(errorMessage(err)); });
    return () => { stale = true; };
  }, [state, page]);

  const s = data?.summary;
  const lastPage = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1;
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Tile label="환불 예정" value={s ? `${s.pending}건` : "-"} sub={s ? `합계 ${won(s.pending_amount)}` : ""} />
        <Tile label="예정일 지남" value={s ? `${s.overdue}건` : "-"} sub="쇼핑몰 결제 시스템 확인 필요" alert={!!s?.overdue} />
        <Tile label="환불·취소 완료" value={s ? `${s.done}건` : "-"} sub="카드는 3~5영업일 뒤 고객 명세서에 반영" />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-xl border border-hairline bg-white p-1" role="group" aria-label="환불 상태">
          {REFUND_STATES.map((f) => (
            <button key={f.value} type="button" aria-pressed={state === f.value} onClick={() => { setState(f.value); setPage(1); }}
              className={cx("rounded-lg px-3 py-1 text-sm font-medium",
                state === f.value ? "bg-primary-soft text-primary" : "text-body hover:bg-surface-soft")}>
              {f.label}
            </button>
          ))}
        </div>
        <span className="text-xs text-muted">취소 환불 = 카드 승인 취소(바로 전액) · 반품 환불 = 회수·검수 뒤. 조회 전용이고, 실제 환불은 쇼핑몰 결제 시스템이 해요.</span>
      </div>

      {error && <Alert>{error}</Alert>}
      <div className="overflow-x-auto rounded-2xl border border-hairline bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-hairline text-sm text-muted">
            <tr>{["구분", "주문", "고객 · 문의", "환불 금액", state === "예정" ? "예정일" : "날짜", "메모"].map((h) => (
              <th key={h} className="whitespace-nowrap px-3 py-3 font-medium">{h}</th>
            ))}</tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {data?.items.map((r) => (
              <tr key={r.id} className={cx(r.inquiry && "cursor-pointer hover:bg-surface-soft", r.overdue && "bg-rose-50/60")}
                onClick={() => r.inquiry && navigate(`/admin/inquiries/${r.inquiry.id}`)}>
                <td className="whitespace-nowrap px-3 py-3">
                  <span className={cx("rounded-full px-2.5 py-0.5 text-xs font-semibold",
                    r.kind === "환불" ? "bg-amber-50 text-amber-800" : "bg-rose-50 text-rose-700")}>
                    {r.kind === "환불" ? "반품 환불" : "취소 환불"}
                  </span>
                  <span className={cx("ml-1.5 rounded-full px-2 py-0.5 text-xs font-medium",
                    r.status === "완료" ? "bg-emerald-50 text-emerald-700" : "bg-primary-soft text-primary")}>{r.status}</span>
                </td>
                <td className="max-w-[15rem] px-3 py-3">
                  <span className="block truncate text-ink">{r.order.product_name}</span>
                  <span className="text-xs text-muted"><span className="font-mono">{r.order.order_number}</span> · 주문 {won(r.order.amount)}</span>
                </td>
                <td className="whitespace-nowrap px-3 py-3">
                  <span className="block text-ink">{r.customer_name ?? "-"}</span>
                  {r.inquiry
                    ? <Link to={`/admin/inquiries/${r.inquiry.id}`} onClick={(e) => e.stopPropagation()}
                        className="font-mono text-xs text-primary hover:underline">{r.inquiry.inquiry_number}</Link>
                    : <span className="text-xs text-muted">연결된 문의 없음</span>}
                </td>
                <td className="whitespace-nowrap px-3 py-3 font-semibold tabular-nums text-ink">
                  {won(r.amount)}<span className="block text-xs font-normal text-muted">{r.method ?? ""}</span>
                </td>
                <td className="whitespace-nowrap px-3 py-3">
                  <span className={r.overdue ? "font-semibold text-rose-700" : "text-body"}>{day(r.at)}</span>
                  {r.overdue && <span className="block text-xs font-semibold text-rose-700">예정일 지남</span>}
                </td>
                <td className="max-w-xs px-3 py-3 text-xs text-muted"><span className="line-clamp-2">{r.memo ?? ""}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data && !error && <p className="p-6 text-center text-muted"><Spinner /></p>}
        {data?.items.length === 0 && (
          <p className="p-6 text-center text-sm text-muted">{state === "예정" ? "진행 중인 환불이 없어요." : "이 조건의 환불 내역이 없어요."}</p>
        )}
      </div>
      {data && data.total > data.size && (
        <div className="flex items-center justify-end gap-2 text-sm text-muted">
          <Button variant="ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>이전</Button>
          <span>{page} / {lastPage}</span>
          <Button variant="ghost" disabled={page >= lastPage} onClick={() => setPage(page + 1)}>다음</Button>
        </div>
      )}
    </div>
  );
}

function Tile({ label, value, sub, alert }: { label: string; value: string; sub: string; alert?: boolean }) {
  return (
    <div className={cx("rounded-2xl border bg-white p-4", alert ? "border-rose-200" : "border-hairline")}>
      <p className="text-sm text-muted">{label}</p>
      <p className={cx("mt-1 text-2xl font-bold tabular-nums", alert ? "text-rose-700" : "text-ink")}>{value}</p>
      <p className={cx("mt-0.5 text-xs", alert ? "text-rose-700" : "text-muted")}>{sub}</p>
    </div>
  );
}
