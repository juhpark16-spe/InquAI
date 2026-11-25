// 주문·배송 (/admin/orders): 주문부터 찾는 화면 (조회 전용, backend/api/customers.py list_orders · get_order)
// - "주문번호 ○○ 어디쯤 왔어요?"처럼 주문이 먼저일 때. 고객 조회(고객 → 주문)와 입구만 다르고 같은 주문 카드
// - 탭: 출고 전 / 배송 중 / 배송 지연(출고됐는데 주문 후 4일 넘게 배송 완료 아님) / 배송 완료 / 반품 / 취소
// - 줄을 누르면 바로 아래에 결제·배송 추적·반품 진행이 펼쳐짐. 바꾸는 일은 문의 상세의 [바로 처리]에서
// - 상담원은 내가 맡은 문의의 고객 주문만
import { Link, useSearchParams } from "react-router";
import { Fragment, useEffect, useState, type FormEvent } from "react";

import { OrderRows, PaymentList, ShipmentList, StockList, SubFold, won } from "../../components/OrderParts";
import { Alert, Badge, Button, Input, Spinner, cx, formatDate, monthDay } from "../../components/ui";
import { errorMessage, opsApi } from "../../services/api";

const SIZE = 30;
const GROUPS = [
  { value: "", label: "전체", key: "all" },
  { value: "ready", label: "출고 전" },
  { value: "shipping", label: "배송 중" },
  { value: "delayed", label: "배송 지연" },
  { value: "delivered", label: "배송 완료" },
  { value: "return", label: "반품" },
  { value: "cancel", label: "취소" },
];
const day = (iso: string) => monthDay(iso, true);

export default function OrdersPage() {
  const [params, setParams] = useSearchParams();
  const group = params.get("group") ?? "";
  const q = params.get("q") ?? "";
  const page = Number(params.get("page") ?? 1);
  const [text, setText] = useState(q);
  const [open, setOpen] = useState<string | null>(null);
  const [data, setData] = useState<Awaited<ReturnType<typeof opsApi.orders>> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    // 탭을 빨리 바꾸면 앞 요청이 늦게 도착해 덮어쓸 수 있어 → 지난 요청의 응답은 버림
    let stale = false;
    setError("");
    opsApi.orders({ group, q, page })
      .then((d) => { if (!stale) setData(d); })
      .catch((err) => { if (!stale) setError(errorMessage(err)); });
    return () => { stale = true; };
  }, [group, q, page]);

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
    setOpen(null);
  };
  function search(e: FormEvent) {
    e.preventDefault();
    update("q", text.trim());
  }
  const lastPage = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">주문·배송</h1>
        <p className="mt-1 text-sm text-muted">
          주문부터 찾을 때 써요 (조회 전용). 줄을 누르면 결제·배송 추적·반품 진행이 바로 아래에 펼쳐져요.
          배송지·옵션 변경, 취소 같은 처리는 그 주문의 문의 상세 [바로 처리]에서 해요.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" className="flex flex-wrap rounded-xl border border-hairline bg-white p-1">
          {GROUPS.map((g) => {
            const count = data?.counts[g.key ?? g.value];
            const alert = g.value === "delayed" && !!count;
            return (
              <button key={g.value} type="button" role="tab" aria-selected={group === g.value} onClick={() => update("group", g.value)}
                className={cx("rounded-lg px-3 py-1.5 text-sm font-semibold",
                  group === g.value ? "bg-primary text-white" : alert ? "text-rose-700 hover:bg-rose-50" : "text-body hover:bg-surface-soft")}>
                {g.label}{count != null && <span className={cx("ml-1.5", group === g.value ? "text-white/80" : alert ? "text-rose-700" : "text-muted")}>{count}</span>}
              </button>
            );
          })}
        </div>
        <form onSubmit={search} className="flex min-w-0 flex-1 gap-2 sm:max-w-md">
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="주문번호·상품·고객 이름·송장번호"
            aria-label="주문 검색" className="flex-1" />
          <Button type="submit">찾기</Button>
          {q && <Button variant="ghost" type="button" onClick={() => { setText(""); update("q", ""); }}>전체</Button>}
        </form>
      </div>
      {group === "delayed" && data && (
        <p className="text-sm text-rose-700">출고됐는데 주문 후 {data.delay_days}일이 지나도 배송 완료가 아닌 주문이에요. 고객이 묻기 전에 택배사 확인을 권해요.</p>
      )}

      {error && <Alert>{error}</Alert>}

      <div className="overflow-x-auto rounded-2xl border border-hairline bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-hairline text-muted">
            <tr>{["주문", "고객", "금액", "주문 상태", "배송", "주문일", "문의"].map((h) => (
              <th key={h} className="whitespace-nowrap px-3 py-3 font-medium">{h}</th>
            ))}</tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {data?.items.map((o) => {
              const isOpen = open === o.order_number;
              return (
                <Fragment key={o.order_number}>
                  <tr className={cx("cursor-pointer hover:bg-surface-soft", isOpen && "bg-primary-soft/40", o.delayed && !isOpen && "bg-rose-50/50")}
                    onClick={() => setOpen(isOpen ? null : o.order_number)} aria-expanded={isOpen}>
                    <td className="max-w-[16rem] px-3 py-3">
                      <span className="block truncate font-semibold text-ink">{o.product_name}{o.quantity > 1 && ` ×${o.quantity}`}</span>
                      <span className="font-mono text-xs text-muted">{o.order_number}</span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3">
                      <Link to={`/admin/customers/${o.customer.id}`} onClick={(e) => e.stopPropagation()} className="text-ink hover:text-primary">{o.customer.name}</Link>
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 tabular-nums text-ink">{won(o.amount)}</td>
                    <td className="whitespace-nowrap px-3 py-3">
                      <Badge value={o.order_status} />
                      {o.returning && <span className="ml-1.5 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800">{o.picked_up ? "반품 회수 완료" : "반품 회수 중"}</span>}
                    </td>
                    <td className="max-w-[14rem] px-3 py-3">
                      <span className={cx("block truncate", o.delayed ? "font-semibold text-rose-700" : "text-body")}>
                        {o.delayed && "지연 · "}{o.shipping_status ?? "-"}
                      </span>
                      {o.tracking_number && <span className="text-xs text-muted">{o.carrier} <span className="font-mono">{o.tracking_number}</span></span>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-muted">{day(o.ordered_at)}</td>
                    <td className="whitespace-nowrap px-3 py-3">
                      {o.latest_inquiry ? (
                        <Link to={`/admin/inquiries/${o.latest_inquiry.id}`} onClick={(e) => e.stopPropagation()} className="text-primary hover:underline">
                          {o.inquiries}건<span className="ml-1 text-xs text-muted">({o.latest_inquiry.status})</span>
                        </Link>
                      ) : <span className="text-muted">-</span>}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr><td colSpan={7} className="bg-surface-soft/60 px-3 py-3"><OrderDetail orderNumber={o.order_number} /></td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
        {!data && !error && <p className="p-6 text-center text-muted"><Spinner /></p>}
        {data?.items.length === 0 && <p className="p-6 text-center text-sm text-muted">이 조건의 주문이 없어요.</p>}
      </div>

      {data && data.total > SIZE && (
        <div className="flex items-center justify-end gap-2 text-sm text-muted">
          <Button variant="ghost" disabled={page <= 1} onClick={() => update("page", String(page - 1))}>이전</Button>
          <span>{page} / {lastPage}</span>
          <Button variant="ghost" disabled={page >= lastPage} onClick={() => update("page", String(page + 1))}>다음</Button>
        </div>
      )}
    </div>
  );
}

/** 펼친 주문: 고객 조회·문의 상세와 같은 주문 카드 + 이 주문의 문의 */
function OrderDetail({ orderNumber }: { orderNumber: string }) {
  const [d, setD] = useState<Awaited<ReturnType<typeof opsApi.order>> | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    opsApi.order(orderNumber).then(setD).catch((err) => setError(errorMessage(err)));
  }, [orderNumber]);
  if (error) return <Alert>{error}</Alert>;
  if (!d) return <p className="p-4 text-center text-muted"><Spinner /></p>;
  const o = d.order;
  return (
    <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="rounded-xl border border-hairline bg-white p-4">
        <OrderRows o={o} />
        {!!o.payments?.length && <SubFold title="결제·환불 내역" open><PaymentList o={o} /></SubFold>}
        {!!o.shipment_events?.length && <SubFold title="배송 추적" open><ShipmentList o={o} /></SubFold>}
        {!!o.option_choices?.length && <SubFold title="옵션별 재고"><StockList o={o} /></SubFold>}
      </div>
      <div className="space-y-3">
        <div className="rounded-xl border border-hairline bg-white p-4 text-sm">
          <p className="text-muted">주문한 고객</p>
          <p className="mt-0.5 font-semibold text-ink">{d.customer.name} <span className="text-xs font-normal text-muted">{d.customer.member ? "회원" : "비회원"}</span></p>
          <Link to={`/admin/customers/${d.customer.id}`} className="mt-1 inline-block text-primary hover:underline">고객 정보 전체 보기 →</Link>
        </div>
        <div className="rounded-xl border border-hairline bg-white p-4 text-sm">
          <p className="mb-1.5 text-muted">이 주문의 문의 {d.inquiries.length}건</p>
          {d.inquiries.length === 0 ? <p className="text-muted">아직 없어요.</p> : (
            <ul className="space-y-1.5">
              {d.inquiries.map((i) => (
                <li key={i.id}>
                  <Link to={`/admin/inquiries/${i.id}`} className="block truncate font-medium text-ink hover:text-primary">{i.title}</Link>
                  <span className="text-xs text-muted">{formatDate(i.created_at)} · {i.status}{i.assigned_to && ` · ${i.assigned_to}`}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
