// 고객 조회 (/admin/customers, /admin/customers/:id): 조회 전용 (backend/api/customers.py)
// - 이름·이메일·전화번호 뒷자리·주문번호로 찾고, 한 명을 누르면 주문(결제·배송 기록)·문의·적립금·쿠폰을 한 화면에
// - 고치는 일(배송지·옵션 변경, 취소 등)은 문의 상세의 [바로 처리]에서. 상담원은 내가 맡은 문의의 고객만 보임
// - 고객 정보를 열면 작업 기록에 '고객 정보 조회'가 남고, 전화번호는 가운데를 가림
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { OrderHead, OrderRows, PaymentList, ShipmentList, StockList, SubFold, won } from "../../components/OrderParts";
import { Alert, Badge, Button, Input, Spinner, cx, formatDate } from "../../components/ui";
import { errorMessage, opsApi, type CustomerDetail } from "../../services/api";

const SIZE = 20;
const OPEN = ["접수", "검토 대기", "담당자 처리"];

function MemberTag({ member }: { member: boolean }) {
  return (
    <span className={cx("rounded-full px-2 py-0.5 text-xs font-medium", member ? "bg-primary-soft text-primary" : "bg-slate-100 text-slate-600")}>
      {member ? "회원" : "비회원"}
    </span>
  );
}

function CustomerList() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const page = Number(params.get("page") ?? 1);
  const [text, setText] = useState(q);
  const [data, setData] = useState<Awaited<ReturnType<typeof opsApi.customers>> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    opsApi.customers({ q, page }).then(setData).catch((err) => setError(errorMessage(err)));
  }, [q, page]);

  function search(e: FormEvent) {
    e.preventDefault();
    setParams(text.trim() ? { q: text.trim() } : {});
  }
  const lastPage = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">고객 조회</h1>
        <p className="mt-1 text-sm text-muted">
          고객의 주문·결제·배송 기록과 문의, 적립금·쿠폰을 한 화면에서 봐요 (조회 전용). 주문 변경·취소는 문의 상세의 [바로 처리]에서 해요.
        </p>
      </div>
      <form onSubmit={search} className="flex max-w-xl gap-2">
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="이름·이메일·전화번호 뒷자리·주문번호" aria-label="고객 검색" className="flex-1" />
        <Button type="submit">찾기</Button>
        {q && <Button variant="ghost" type="button" onClick={() => { setText(""); setParams({}); }}>전체 보기</Button>}
      </form>

      {error && <Alert>{error}</Alert>}

      <div className="overflow-x-auto rounded-2xl border border-hairline bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-hairline text-sm text-muted">
            <tr>{["고객", "연락처", "주문", "최근 주문", "문의"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-3 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {data?.items.map((c) => (
              <tr key={c.id} className="cursor-pointer hover:bg-surface-soft" onClick={() => navigate(`/admin/customers/${c.id}`)}>
                <td className="whitespace-nowrap px-3 py-3">
                  <Link to={`/admin/customers/${c.id}`} onClick={(e) => e.stopPropagation()} className="font-semibold text-ink hover:text-primary">{c.name}</Link>
                  <span className="ml-2"><MemberTag member={c.member} /></span>
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-body">{c.email}<span className="block text-xs text-muted">{c.phone ?? "-"}</span></td>
                <td className="whitespace-nowrap px-3 py-3 tabular-nums">{c.orders}건</td>
                <td className="whitespace-nowrap px-3 py-3 text-muted">{c.last_order_at ? formatDate(c.last_order_at) : "-"}</td>
                <td className="whitespace-nowrap px-3 py-3">
                  {c.inquiries}건
                  {c.open_inquiries > 0 && <span className="ml-1.5 rounded-full bg-primary-soft px-2 py-0.5 text-xs font-semibold text-primary">처리 중 {c.open_inquiries}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data && !error && <p className="p-6 text-center text-muted"><Spinner /></p>}
        {data?.items.length === 0 && <p className="p-6 text-center text-sm text-muted">{q ? `'${q}'(으)로 찾은 고객이 없어요.` : "볼 수 있는 고객이 없어요."}</p>}
      </div>
      {data && (
        <div className="flex items-center justify-between text-sm text-muted">
          <span>총 {data.total.toLocaleString()}명</span>
          {data.total > SIZE && (
            <div className="flex items-center gap-2">
              <Button variant="ghost" disabled={page <= 1} onClick={() => setParams({ ...(q ? { q } : {}), page: String(page - 1) })}>이전</Button>
              <span>{page} / {lastPage}</span>
              <Button variant="ghost" disabled={page >= lastPage} onClick={() => setParams({ ...(q ? { q } : {}), page: String(page + 1) })}>다음</Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="rounded-2xl border border-hairline bg-white p-5">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-[17px] font-semibold text-ink">{title}</h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

function CustomerView({ id }: { id: number }) {
  const [c, setC] = useState<CustomerDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    setC(null);
    setError("");
    opsApi.customer(id).then(setC).catch((err) => setError(errorMessage(err)));
  }, [id]);

  if (error) return <div className="space-y-3"><Link to="/admin/customers" className="text-sm text-primary">← 고객 목록</Link><Alert>{error}</Alert></div>;
  if (!c) return <p className="p-6 text-center text-muted"><Spinner /></p>;
  const hidden = c.inquiry_total - c.inquiries.length;
  const usable = c.coupons.filter((x) => x.state === "사용 가능");

  return (
    <div className="space-y-4">
      <Link to="/admin/customers" className="text-sm text-primary hover:underline">← 고객 목록</Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="page-title flex flex-wrap items-center gap-2">{c.name} <MemberTag member={c.member} /></h1>
          <p className="mt-1 text-sm text-muted">{c.email} · {c.phone ?? "전화번호 없음"} · 등록 {formatDate(c.since)}</p>
        </div>
        {(c.negative_ratings > 0 || c.negative_inquiries >= 2) && (
          <span className="rounded-full bg-rose-50 px-3 py-1.5 text-sm font-semibold text-rose-700">
            응대에 신경 쓸 고객 · 👎 {c.negative_ratings} · 부정 문의 {c.negative_inquiries}
          </span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        {[
          ["주문", `${c.orders.length}건`],
          ["문의", `${c.inquiry_total}건`],
          ["적립금", c.points_balance === null ? "-" : won(c.points_balance) + (c.points_pending ? ` (+${won(c.points_pending)} 예정)` : "")],
          ["쓸 수 있는 쿠폰", `${usable.length}장`],
        ].map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-hairline bg-white px-4 py-3">
            <p className="text-xs text-muted">{label}</p>
            <p className="mt-0.5 text-lg font-semibold tabular-nums text-ink">{value}</p>
          </div>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_24rem]">
        <Section title={`주문 ${c.orders.length}건`}>
          {c.orders.length === 0 && <p className="text-sm text-muted">주문이 없어요.</p>}
          <div className="space-y-3">
            {c.orders.map((o, i) => (
              <details key={o.order_number} open={i === 0} className="group rounded-xl border border-hairline p-4">
                <summary className="flex cursor-pointer list-none items-start justify-between gap-3">
                  <OrderHead o={o} />
                  <span className="flex shrink-0 items-center gap-2">
                    {o.duplicate_payment && <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700">중복 결제 의심</span>}
                    <Badge value={o.order_status} />
                    <span className="text-sm text-muted"><span className="group-open:hidden">▾</span><span className="hidden group-open:inline">▴</span></span>
                  </span>
                </summary>
                <div className="mt-3 border-t border-hairline pt-3">
                  <OrderRows o={o} />
                  {!!o.payments?.length && <SubFold title="결제·환불 내역"><PaymentList o={o} /></SubFold>}
                  {!!o.shipment_events?.length && <SubFold title="배송 추적"><ShipmentList o={o} /></SubFold>}
                  {!!o.option_choices?.length && <SubFold title="옵션별 재고"><StockList o={o} /></SubFold>}
                </div>
              </details>
            ))}
          </div>
        </Section>

        <div className="space-y-4">
          <Section title="문의">
            {c.inquiries.length === 0 && hidden === 0 && <p className="text-sm text-muted">문의가 없어요.</p>}
            <ul className="divide-y divide-hairline">
              {c.inquiries.map((i) => (
                <li key={i.id} className="py-2">
                  <Link to={`/admin/inquiries/${i.id}`} className="block truncate text-sm font-semibold text-ink hover:text-primary">{i.title}</Link>
                  <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    <span className={cx("rounded-full px-2 py-0.5 font-medium", OPEN.includes(i.status) ? "bg-primary-soft text-primary" : "bg-slate-100 text-slate-600")}>{i.status}</span>
                    {formatDate(i.created_at)}{i.order_number && <> · <span className="font-mono">{i.order_number}</span></>}
                    {i.assigned_to && <> · {i.assigned_to}</>}
                  </span>
                </li>
              ))}
            </ul>
            {hidden > 0 && <p className="mt-2 text-xs text-muted">다른 상담원이 맡은 문의 {hidden}건은 보이지 않아요.</p>}
          </Section>

          <Section title="쿠폰">
            {c.coupons.length === 0 && <p className="text-sm text-muted">가진 쿠폰이 없어요.</p>}
            <ul className="space-y-1.5 text-sm">
              {c.coupons.map((x, i) => (
                <li key={i} className={cx("flex items-baseline justify-between gap-2", x.state !== "사용 가능" && "text-muted")}>
                  <span className="min-w-0">
                    <span className={cx("font-medium", x.state === "사용 가능" && "text-ink")}>{x.name}</span>
                    <span className="block text-xs text-muted">{x.benefit}{x.min_amount ? ` · ${won(x.min_amount)} 이상` : ""} · ~{formatDate(x.expires_at)}</span>
                  </span>
                  <span className={cx("shrink-0 text-xs font-semibold", x.state === "사용 가능" ? "text-emerald-700" : "text-muted")}>{x.state}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="적립금 내역" aside={<span className="text-xs text-muted">최근 5건</span>}>
            {c.point_history.length === 0 && <p className="text-sm text-muted">내역이 없어요.</p>}
            <ul className="space-y-1.5 text-sm">
              {c.point_history.map((p, i) => (
                <li key={i} className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate">{p.reason}{p.status === "예정" && <span className="text-xs text-amber-700"> (예정)</span>}
                    <span className="block text-xs text-muted">{formatDate(p.at)}</span></span>
                  <span className={cx("shrink-0 font-semibold tabular-nums", p.amount >= 0 ? "text-emerald-700" : "text-rose-700")}>
                    {p.amount >= 0 ? "+" : ""}{p.amount.toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          </Section>
        </div>
      </div>
    </div>
  );
}

export default function CustomersPage() {
  const { id } = useParams();
  return id ? <CustomerView id={Number(id)} /> : <CustomerList />;
}
