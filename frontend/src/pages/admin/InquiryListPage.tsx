// 문의 목록 (/admin/inquiries): 필터·검색·정렬·페이지. 조건은 주소(?status=...)에 남겨 새로고침해도 유지됩니다.
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import { Alert, Badge, Button, Input, Select, Spinner, formatDate } from "../../components/ui";
import { errorMessage, inquiryApi } from "../../services/api";
import { CATEGORIES, DECISIONS, STATUSES, URGENCIES, type InquiryListItem, type Page } from "../../services/types";

const SIZE = 20;

export default function InquiryListPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<Page<InquiryListItem> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState(params.get("q") ?? "");

  const page = Number(params.get("page") ?? 1);
  const key = params.toString();

  useEffect(() => {
    setLoading(true);
    setError("");
    inquiryApi
      .list({
        category: params.get("category") ?? "", urgency: params.get("urgency") ?? "",
        status: params.get("status") ?? "", decision: params.get("decision") ?? "", open: params.get("open") ?? "",
        assigned_to: params.get("assigned_to") ?? "", q: params.get("q") ?? "",
        sort: (params.get("sort") as "urgency" | "-created_at") ?? "urgency", page, size: SIZE,
      })
      .then(setData)
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  function update(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    if (name !== "page") next.delete("page"); // 조건이 바뀌면 첫 페이지로
    setParams(next);
  }

  function search(e: FormEvent) {
    e.preventDefault();
    update("q", q.trim());
  }

  const filter = (name: string, label: string, options: readonly string[]) => (
    <Select value={params.get(name) ?? ""} onChange={(e) => update(name, e.target.value)} aria-label={label}>
      <option value="">{label} 전체</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </Select>
  );

  const lastPage = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">문의 관리</h1>
          <p className="text-sm text-slate-500">
            {user?.role === "agent" ? "나에게 배정된 문의만 보입니다." : "긴급도 높은 문의가 위에 옵니다."}
          </p>
        </div>
        <form onSubmit={search} className="flex gap-2">
          <Input className="w-64" placeholder="제목·내용·문의 번호·이메일" value={q} onChange={(e) => setQ(e.target.value)} />
          <Button type="submit">검색</Button>
        </form>
      </div>

      <div className="flex flex-wrap gap-2">
        <label className="flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-700">
          <input type="checkbox" checked={params.get("open") === "true"} onChange={(e) => update("open", e.target.checked ? "true" : "")} />
          미처리만
        </label>
        {filter("status", "상태", STATUSES)}
        {filter("urgency", "긴급도", URGENCIES)}
        {filter("category", "유형", CATEGORIES)}
        {filter("decision", "처리 방식", DECISIONS)}
        {user?.role === "admin" && (
          <Select value={params.get("assigned_to") ?? ""} onChange={(e) => update("assigned_to", e.target.value)} aria-label="배정">
            <option value="">배정 전체</option>
            <option value="none">미배정</option>
            <option value="me">나에게 배정</option>
          </Select>
        )}
        <Select value={params.get("sort") ?? "urgency"} onChange={(e) => update("sort", e.target.value === "urgency" ? "" : e.target.value)} aria-label="정렬">
          <option value="urgency">긴급도순</option>
          <option value="-created_at">최신순</option>
        </Select>
        {key && <Button variant="ghost" onClick={() => { setQ(""); setParams(new URLSearchParams()); }}>조건 초기화</Button>}
      </div>

      {error && <Alert>{error}</Alert>}

      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs text-slate-500">
            <tr>
              {["문의 번호", "제목", "고객", "유형", "긴급도", "감정", "처리 방식", "상태", "담당", "접수 시각"].map((h) => (
                <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data?.items.map((i) => (
              <tr key={i.id} className="cursor-pointer hover:bg-slate-50" onClick={() => navigate(`/admin/inquiries/${i.id}`)}>
                <td className="whitespace-nowrap px-3 py-2 font-mono text-xs">
                  <Link to={`/admin/inquiries/${i.id}`} onClick={(e) => e.stopPropagation()} className="text-indigo-600 hover:underline">
                    {i.inquiry_number}
                  </Link>
                </td>
                <td className="max-w-xs truncate px-3 py-2">{i.title}</td>
                <td className="whitespace-nowrap px-3 py-2">{i.customer_name}</td>
                <td className="whitespace-nowrap px-3 py-2">{i.category ?? "-"}</td>
                <td className="px-3 py-2"><Badge value={i.urgency} /></td>
                <td className="px-3 py-2"><Badge value={i.sentiment} /></td>
                <td className="px-3 py-2"><Badge value={i.decision} /></td>
                <td className="px-3 py-2"><Badge value={i.status} /></td>
                <td className="whitespace-nowrap px-3 py-2 text-slate-600">{i.assigned_to?.display_name ?? "-"}</td>
                <td className="whitespace-nowrap px-3 py-2 text-slate-500">{formatDate(i.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {loading && <p className="p-6 text-center text-slate-500"><Spinner /></p>}
        {!loading && data?.items.length === 0 && <p className="p-6 text-center text-sm text-slate-500">조건에 맞는 문의가 없습니다.</p>}
      </div>

      {data && (
        <div className="flex items-center justify-between text-sm text-slate-600">
          <span>총 {data.total}건</span>
          <div className="flex items-center gap-2">
            <Button variant="ghost" disabled={page <= 1} onClick={() => update("page", String(page - 1))}>이전</Button>
            <span>{page} / {lastPage}</span>
            <Button variant="ghost" disabled={page >= lastPage} onClick={() => update("page", String(page + 1))}>다음</Button>
          </div>
        </div>
      )}
    </div>
  );
}
