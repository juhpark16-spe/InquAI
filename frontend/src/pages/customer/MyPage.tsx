// 내 쇼핑 (/my, 쇼핑몰 로그인 고객): 내 주문에서 바로 문의하기 + 내 문의 (조회 비밀번호 없이)
import { useCallback, useEffect, useState } from "react";
import { Link, Navigate } from "react-router";

import { useShop } from "../../auth/ShopProvider";
import InquiryThreads from "../../components/InquiryThreads";
import { Alert, Card, Spinner, formatDate } from "../../components/ui";
import { errorMessage, shopApi } from "../../services/api";
import type { InquiryPublic, ShopOrder } from "../../services/types";

const STATUS_STYLE: Record<string, string> = {
  "결제 완료": "bg-slate-100 text-slate-600", "상품 준비 중": "bg-amber-100 text-amber-800", 출고: "bg-sky-100 text-sky-800",
  "배송 중": "bg-sky-100 text-sky-800", "배송 완료": "bg-emerald-100 text-emerald-700", 취소: "bg-slate-200 text-slate-500",
};

function OrderCard({ o }: { o: ShopOrder }) {
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-xl border border-hairline bg-white p-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={`rounded-full px-2 py-0.5 font-medium ${STATUS_STYLE[o.order_status] ?? "bg-slate-100 text-slate-600"}`}>{o.order_status}</span>
          <span className="font-mono text-slate-500">{o.order_number}</span>
          <span className="text-slate-400">{formatDate(o.ordered_at)}</span>
        </div>
        <p className="mt-1 truncate font-semibold text-ink">{o.product_name}</p>
        <p className="text-sm text-slate-500">
          {o.amount.toLocaleString()}원{o.shipping_status && o.shipping_status !== o.order_status && ` · ${o.shipping_status}`}
          {o.inquiry_count > 0 && <span className="ml-2 text-primary">문의 {o.inquiry_count}건</span>}
        </p>
      </div>
      <Link to={`/inquiry?order=${encodeURIComponent(o.order_number)}`}
        className="inline-flex min-h-10 items-center rounded-xl border border-hairline bg-white px-4 text-sm font-semibold text-ink hover:bg-surface-card">
        이 주문 문의하기
      </Link>
    </li>
  );
}

export default function MyPage() {
  const { customer, loading } = useShop();
  const [orders, setOrders] = useState<ShopOrder[] | null>(null);
  const [items, setItems] = useState<InquiryPublic[] | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const loadInquiries = useCallback(async () => {
    const r = await shopApi.inquiries();
    setItems(r.items);
    setNotice(r.notice);
  }, []);

  useEffect(() => {
    if (!customer) return;
    shopApi.orders().then(setOrders).catch((err) => setError(errorMessage(err)));
    loadInquiries().catch((err) => setError(errorMessage(err)));
  }, [customer, loadInquiries]);

  if (loading) return <p className="text-center text-slate-500"><Spinner /></p>;
  if (!customer) return <Navigate to="/shop/login" replace state={{ from: "/my" }} />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="page-title">{customer.name}님의 쇼핑</h1>
        <p className="text-sm text-muted">주문에서 바로 문의하면 주문번호가 자동으로 들어가 더 빨리 확인해 드려요.</p>
      </div>
      {error && <Alert>{error}</Alert>}

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-ink">내 주문</h2>
        {!orders && !error && <p className="text-center text-slate-500"><Spinner /></p>}
        {orders?.length === 0 && <p className="text-sm text-muted">주문 내역이 없습니다.</p>}
        <ul className="space-y-2">{orders?.map((o) => <OrderCard key={o.order_number} o={o} />)}</ul>
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ink">내 문의 {items && <span className="text-sm font-normal text-muted">{items.length}건</span>}</h2>
          <Link to="/inquiry" className="text-sm font-semibold text-primary hover:underline">새 문의</Link>
        </div>
        {items?.length === 0 && <Card><p className="text-sm text-muted">아직 남긴 문의가 없어요.</p></Card>}
        {items && items.length > 0 && (
          <InquiryThreads items={items} notice={notice} reload={loadInquiries} actions={{
            rate: (n, id, helpful) => shopApi.rate(id, n, helpful),
            followUp: (n, text, tokens) => shopApi.followUp(n, text, tokens),
          }} />
        )}
      </section>
    </div>
  );
}
