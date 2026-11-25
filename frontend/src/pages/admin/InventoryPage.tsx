// 재고 현황 (/admin/inventory): 상품 옵션별 재고 (조회 전용, backend/api/customers.py list_inventory)
// - AI 초안·상담원이 '재입고 언제 돼요?', '다른 사이즈 있어요?'에 답할 때 쓰는 근거와 같은 표
// - 재고를 바꾸는 일은 쇼핑몰 시스템의 몫. 취소·옵션 변경으로 생기는 재고 변화는 문의 처리에서 자동 반영
import { useEffect, useState } from "react";

import { Alert, Input, Spinner, cx, monthDay } from "../../components/ui";
import { errorMessage, opsApi } from "../../services/api";

const FILTERS = [
  { value: "", label: "전체" },
  { value: "sold_out", label: "품절" },
  { value: "low", label: "재고 적음" },
];

export default function InventoryPage() {
  const [only, setOnly] = useState("");
  const [q, setQ] = useState("");
  const [data, setData] = useState<Awaited<ReturnType<typeof opsApi.inventory>> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stale = false;   // 앞 요청의 늦은 응답은 버림
    const timer = setTimeout(() => {
      opsApi.inventory({ only, q: q.trim() })
        .then((d) => { if (!stale) { setData(d); setError(""); } })
        .catch((err) => { if (!stale) setError(errorMessage(err)); });
    }, 250);
    return () => { stale = true; clearTimeout(timer); };
  }, [only, q]);

  const s = data?.summary;
  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">재고 현황</h1>
        <p className="mt-1 text-sm text-muted">
          상품 옵션별 재고예요 (조회 전용). AI 초안과 문의 상세의 '옵션별 재고'가 이 표를 근거로 재입고·옵션 변경을 안내해요.
          {data && ` 재고 ${data.low_stock}개 이하는 '적음'으로 보여요.`}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" className="flex rounded-xl border border-hairline bg-white p-1">
          {FILTERS.map((f) => {
            const count = !s ? null : f.value === "sold_out" ? s.sold_out : f.value === "low" ? s.low : s.options;
            return (
              <button key={f.value} type="button" role="tab" aria-selected={only === f.value} onClick={() => setOnly(f.value)}
                className={cx("rounded-lg px-3 py-1.5 text-sm font-semibold",
                  only === f.value ? "bg-primary text-white" : "text-body hover:bg-surface-soft")}>
                {f.label}{count != null && <span className={cx("ml-1.5", only === f.value ? "text-white/80" : "text-muted")}>{count}</span>}
              </button>
            );
          })}
        </div>
        <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="상품명·옵션으로 찾기" aria-label="재고 검색" className="max-w-xs" />
      </div>

      {error && <Alert>{error}</Alert>}
      {!data && !error && <p className="p-6 text-center text-muted"><Spinner /></p>}
      {/* 한 줄 = 옵션 하나. 상품 이름은 그 상품의 첫 줄에만 (상품 사이는 굵은 선) */}
      {data && data.products.length > 0 && (
        <div className="overflow-x-auto rounded-2xl border border-hairline bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-hairline text-muted">
              <tr>{["상품", "옵션", "재고", "상태", "재입고"].map((h) => (
                <th key={h} className={cx("whitespace-nowrap px-4 py-2.5 font-medium", h === "재고" && "text-right")}>{h}</th>
              ))}</tr>
            </thead>
            {data.products.map((p) => (
              <tbody key={p.product} className="border-t-2 border-hairline first-of-type:border-t-0">
                {p.options.map((o, i) => (
                  <tr key={o.option} className={cx(i > 0 && "border-t border-hairline/60", o.sold_out && "bg-rose-50/50")}>
                    <td className="whitespace-nowrap px-4 py-2 font-semibold text-ink">{i === 0 ? p.product : ""}</td>
                    <td className="whitespace-nowrap px-4 py-2 text-body">{o.option}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-ink">{o.stock}개</td>
                    <td className="whitespace-nowrap px-4 py-2">
                      {o.sold_out ? <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-semibold text-rose-700">품절</span>
                        : o.low ? <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800">재고 적음</span>
                          : <span className="text-xs text-muted">충분</span>}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 text-muted">
                      {o.sold_out ? (o.restock_at ? `${monthDay(o.restock_at)} 예정` : "미정") : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            ))}
          </table>
        </div>
      )}
      {data?.products.length === 0 && <p className="rounded-2xl border border-hairline bg-white p-6 text-center text-sm text-muted">이 조건의 옵션이 없어요.</p>}
    </div>
  );
}
