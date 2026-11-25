// 주문 정보 부품: 문의 상세의 '주문 정보' 카드와 고객 조회 화면이 함께 씀
// (주문 상태·취소/반품 가능 기한·결제·환불·배송 추적·옵션별 재고)
import { useState, type ReactNode } from "react";

import { Badge, cx, formatDate } from "./ui";
import Icon from "./Icon";
import type { OrderCard } from "../services/types";

export function daysLeft(iso: string) {
  const d = Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000);
  return d >= 0 ? `D-${d}` : `${-d}일 지남`;
}

export const won = (n: number | null) => (n === null ? "-" : `${n.toLocaleString()}원`);

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-ink">{children}</dd>
    </>
  );
}

/** 가능/불가를 색 있는 표시로 (초록 = 가능, 회색 = 불가) */
export function YesNo({ ok, yes, no }: { ok: boolean | null; yes: string; no: string }) {
  if (ok === null) return <span className="text-slate-500">-</span>;
  return (
    <span className={cx("inline-block rounded-md px-2 py-0.5 text-sm font-semibold",
      ok ? "bg-emerald-100 text-emerald-800" : "bg-slate-200 text-slate-700")}>
      {ok ? `✓ ${yes}` : `✕ ${no}`}
    </span>
  );
}

export const shortDate = (iso: string | null | undefined) => (iso ? formatDate(iso) : "-");

/** 환불 진행: 결제 내역의 환불 줄 (예정이면 날짜, 예정일이 지났으면 빨강) */
export function RefundLine({ o }: { o: OrderCard }) {
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

/** 배송 묶음: 배송 단계 · 송장번호[복사] · 택배사 확인(배송조회·고객센터) · 담당 기사 (services/carriers.py) */
function ShippingRows({ o }: { o: OrderCard }) {
  return (
    <>
      <Row label="배송">
        {o.shipping_status ?? "-"}
        {o.carrier && <span className="text-muted"> · {o.carrier}</span>}
      </Row>
      {o.tracking_number && <Row label="송장번호"><span className="font-mono font-semibold">{o.tracking_number}</span> <CopyButton text={o.tracking_number} /></Row>}
      {o.carrier_info && (
        <Row label="택배사 확인">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <a href={o.carrier_info.tracking_url} target="_blank" rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-lg border border-hairline px-2 py-0.5 text-xs font-semibold text-primary hover:border-primary">
              배송조회 열기 <Icon name="external" className="h-3.5 w-3.5" />
            </a>
            <span className="text-xs text-muted">고객센터 <span className="font-mono text-body">{o.carrier_info.phone}</span></span>
          </span>
          {o.driver && (
            <span className="mt-1 block text-xs text-muted">
              담당 기사 <span className="text-body">{o.driver.name}</span> <span className="font-mono">{o.driver.phone}</span> · 상담원 확인용 (고객 답변에 넣지 않기)
            </span>
          )}
        </Row>
      )}
    </>
  );
}

function CancelRow({ o }: { o: OrderCard }) {
  return (
    <Row label="취소">
      {o.order_status === "취소" ? <span className="font-semibold text-slate-700">이미 취소된 주문</span>
        : <YesNo ok={o.cancellable} yes="가능 (출고 전)" no="불가 (출고됨)" />}
    </Row>
  );
}

function ReturnRow({ o }: { o: OrderCard }) {
  return (
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
  );
}

/** 주문 한 건의 상세 (전체): 상태·결제·배송·반품·환불·취소/반품 가능 기한. 주문·배송·고객 조회 화면, 문의 상세의 '주문 전체 정보' */
export function OrderRows({ o }: { o: OrderCard }) {
  return (
    <dl className="grid grid-cols-[5.5rem_1fr] items-center gap-x-3 gap-y-1.5 text-sm">
      <Row label="주문 상태"><Badge value={o.order_status} /></Row>
      <ShippingRows o={o} />
      {o.payment_method && <Row label="결제">{o.payment_method} <span className="text-muted">· {shortDate(o.paid_at)}</span></Row>}
      <Row label="주문일">{formatDate(o.ordered_at)}</Row>
      {o.delivered_at && <Row label="배송 완료">{formatDate(o.delivered_at)}</Row>}
      <RefundLine o={o} />
      <CancelRow o={o} />
      <ReturnRow o={o} />
      {o.shipping_address && <Row label="배송지">{o.shipping_address}</Row>}
    </dl>
  );
}

/** 한 줄 요약: 택배사 · 주문 상태(배송 단계) · 취소 가능 · 반품 기한 (문의 상세 주문 정보 맨 위) */
export function OrderStatusLine({ o }: { o: OrderCard }) {
  const ret = o.order_status === "취소" ? null
    : o.return_requested_at ? (o.picked_up_at ? "반품 회수 완료" : "반품 회수 중")
      : o.return_until ? (o.returnable ? `반품 ${daysLeft(o.return_until)}` : "반품 기한 지남") : null;
  const parts = [
    o.carrier,
    `${o.order_status}${o.shipping_status && o.shipping_status !== o.order_status ? ` (${o.shipping_status})` : ""}`,
    o.order_status === "취소" ? null : o.cancellable ? "취소 가능" : "취소 불가",
    ret,
  ].filter(Boolean);
  return <p className="mb-2 rounded-lg bg-surface-soft px-3 py-1.5 text-sm font-medium text-ink">{parts.join(" · ")}</p>;
}

/** 문의 유형에 맞춘 핵심 칸 (3~4줄). 나머지는 '주문 전체 정보'로 접음 */
export function OrderFocus({ o, category }: { o: OrderCard; category: string | null }) {
  const qty = o.quantity ?? 1;
  const rows = (() => {
    switch (category) {
      case "배송":
        return <ShippingRows o={o} />;
      case "주문 취소":
        return (<>
          <CancelRow o={o} />
          <Row label="결제">{won(o.amount)}{o.payment_method && <span className="text-muted"> · {o.payment_method}</span>}</Row>
          {qty > 1 && <Row label="수량">{qty}개 <span className="text-xs text-muted">· 출고 전이면 일부만 취소 가능 ([부분 취소])</span></Row>}
        </>);
      case "반품·환불":
      case "교환":
        return (<>
          <ReturnRow o={o} />
          <RefundLine o={o} />
          {o.refund_preview != null && !(o.payments ?? []).some((p) => p.kind === "환불") && (
            <Row label="환불 예정">{won(o.refund_preview)}{o.return_reason && <span className="text-muted"> · {o.return_reason}</span>}</Row>
          )}
          {!o.return_requested_at && <Row label="배송">{o.shipping_status ?? "-"}{o.delivered_at && <span className="text-muted"> · 완료 {shortDate(o.delivered_at)}</span>}</Row>}
        </>);
      case "결제":
        return (<>
          <Row label="결제">{won(o.amount)}{o.payment_method && <span className="text-muted"> · {o.payment_method} · {shortDate(o.paid_at)}</span>}</Row>
          <RefundLine o={o} />
          <CancelRow o={o} />
        </>);
      default:
        return (<>
          <Row label="주문일">{formatDate(o.ordered_at)}</Row>
          <ShippingRows o={o} />
        </>);
    }
  })();
  // 배송지: 배송 문의이거나 출고 전(아직 바꿀 수 있음)이면 핵심 칸에 (배송지 변경 문의를 바로 처리하게)
  const address = o.shipping_address && (category === "배송" || o.cancellable) ? <Row label="배송지">{o.shipping_address}</Row> : null;
  return <dl className="grid grid-cols-[5.5rem_1fr] items-center gap-x-3 gap-y-1.5 text-sm">{rows}{address}</dl>;
}

/** 작은 복사 버튼 (송장번호: 택배사에 전화할 때 바로 불러 주게) */
function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="ml-1 rounded-md border border-hairline px-1.5 py-px text-xs text-muted hover:text-ink"
      onClick={() => navigator.clipboard?.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1500); }).catch(() => {})}>
      {done ? "복사됨 ✓" : "복사"}
    </button>
  );
}

/** 접는 소제목 (결제·환불 내역, 배송 추적 등) */
export function SubFold({ title, open, children }: { title: string; open?: boolean; children: ReactNode }) {
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
export function stockText(c: NonNullable<OrderCard["option_choices"]>[number]) {
  if (c.sold_out) {
    if (!c.restock_at) return "품절 · 재입고 미정";
    const d = new Date(c.restock_at);
    return `품절 · 재입고 ${d.getMonth() + 1}/${d.getDate()} 예정`;
  }
  return `재고 ${c.stock}개${c.low ? " (적음)" : ""}`;
}

/** 같은 상품의 옵션별 재고 (교환·옵션 변경 문의에 바로 안내할 수 있게) */
export function StockList({ o }: { o: OrderCard }) {
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
export function PaymentList({ o }: { o: OrderCard }) {
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
export function ShipmentList({ o }: { o: OrderCard }) {
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
export function OrderHead({ o }: { o: OrderCard }) {
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
