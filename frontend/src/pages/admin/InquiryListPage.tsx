// 문의 목록 (/admin/inquiries): 필터·검색·정렬·페이지. 조건은 주소(?status=...)에 남겨 새로고침해도 유지됩니다.
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import { Alert, Badge, Button, Select, Spinner, formatDate } from "../../components/ui";
import { errorMessage, inquiryApi } from "../../services/api";
import { CATEGORIES, DECISIONS, STATUSES, URGENCIES, type InquiryListItem, type Page } from "../../services/types";

const SIZE = 20;

/** AI 유형 분류 확신도: 막대 10칸 + 숫자. 0.8 미만은 주황(사람이 확인할 문의) */
/** 유형 옆 표시: AI 확신도가 낮을 때만 (0.8 미만이면 담당자 확인). 확신도 숫자는 상세 화면 'AI 분석'에서 봄 */
function LowConfidence({ value }: { value: number | null }) {
  if (value === null || value >= 0.8) return null;
  return (
    <span className="ml-1.5 rounded bg-amber-100 px-1.5 py-0.5 text-xs font-semibold text-amber-800" title={`AI 유형 분류 확신도 ${Math.round(value * 100)}% (0.8 미만)`}>
      확인 필요
    </span>
  );
}

export default function InquiryListPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<Page<InquiryListItem> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  // 검색은 화면 위쪽 검색창(AdminLayout)에서 함 → 주소의 q 로 들어옴. 여기서는 검색어 표시·지우기만
  const q = params.get("q") ?? "";

  const page = Number(params.get("page") ?? 1);
  const key = params.toString();

  useEffect(() => {
    setLoading(true);
    setError("");
    inquiryApi
      .list({
        category: params.get("category") ?? "", urgency: params.get("urgency") ?? "",
        status: params.get("status") ?? "", decision: params.get("decision") ?? "", open: params.get("open") ?? "", overdue: params.get("overdue") ?? "",
        recheck: params.get("recheck") ?? "", assigned_to: params.get("assigned_to") ?? "", q: params.get("q") ?? "",
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
          <h1 className="page-title">문의 관리</h1>
          <p className="text-sm text-slate-500">
            {user?.role === "agent" ? "나에게 배정된 문의만 보입니다." : "긴급도 높은 문의가 위에 옵니다."}
          </p>
        </div>
        {q && (
          <span className="inline-flex items-center gap-2 rounded-xl border border-primary/30 bg-primary-soft py-1.5 pl-3 pr-1.5 text-sm text-primary">
            검색어: <b className="font-semibold">{q}</b>
            <button type="button" onClick={() => update("q", "")} aria-label="검색어 지우기"
              className="rounded-lg px-2 py-0.5 hover:bg-white">✕</button>
          </span>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        <label className="flex min-h-11 items-center gap-1.5 rounded-xl border border-hairline bg-white px-3 text-sm text-ink">
          <input type="checkbox" checked={params.get("open") === "true"} onChange={(e) => update("open", e.target.checked ? "true" : "")} />
          미처리만
        </label>
        <label className="flex min-h-11 items-center gap-1.5 rounded-xl border border-hairline bg-white px-3 text-sm text-ink">
          <input type="checkbox" checked={params.get("overdue") === "true"} onChange={(e) => update("overdue", e.target.checked ? "true" : "")} />
          기한 초과만
        </label>
        <label className="flex min-h-11 items-center gap-1.5 rounded-xl border border-hairline bg-white px-3 text-sm text-ink"
          title="'확인 후 다시 안내드리겠습니다'를 먼저 보내고 아직 다시 안내하지 않은 문의 (다시 안내 기한이 가까운 순)">
          <input type="checkbox" checked={params.get("recheck") === "true"} onChange={(e) => update("recheck", e.target.checked ? "true" : "")} />
          다시 안내할 문의만
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
        {key && <Button variant="ghost" onClick={() => setParams(new URLSearchParams())}>조건 초기화</Button>}
      </div>

      {error && <Alert>{error}</Alert>}

      <div className="overflow-x-auto rounded-2xl border border-hairline bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-hairline text-sm text-muted">
            <tr>
              {/* AI 확신도·감정·처리 방식 열은 뺌 (확신도가 낮으면 유형 옆에 '확인 필요', 감정은 긴급도에 반영,
                  처리 방식은 상태와 거의 같음 → 필터로만). 상담원은 자기 문의만 보여 '담당' 열 없음 */}
              {["문의 번호", "제목", "고객", "유형", "긴급도", "상태", ...(isAdmin ? ["담당"] : []), "접수 시각"].map((h) => (
                <th key={h} className="whitespace-nowrap px-3 py-3 font-medium">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {data?.items.map((i) => (
              <tr key={i.id} className="cursor-pointer hover:bg-surface-soft" onClick={() => navigate(`/admin/inquiries/${i.id}`)}>
                <td className="whitespace-nowrap px-3 py-3 font-mono text-sm">
                  <Link to={`/admin/inquiries/${i.id}`} onClick={(e) => e.stopPropagation()} className="text-indigo-600 hover:underline">
                    {i.inquiry_number}
                  </Link>
                </td>
                <td className="max-w-xs truncate px-3 py-3">{i.title}</td>
                <td className="whitespace-nowrap px-3 py-3">{i.customer_name}</td>
                <td className="whitespace-nowrap px-3 py-3">{i.category ?? "-"}<LowConfidence value={i.confidence} /></td>
                {/* 끝난 문의(자동 처리·완료)의 긴급도는 더 이상 급하지 않으니 회색 글자로 */}
                <td className="px-3 py-3">{i.status === "완료" || i.status === "자동 처리" ? <span className="text-xs text-muted">{i.urgency ?? "-"}</span> : <Badge value={i.urgency} />}</td>
                <td className="whitespace-nowrap px-3 py-3">
                  <Badge value={i.status} />
                  {i.overdue && <span className="ml-1 text-xs font-semibold text-rose-700" title={`답변 기한 ${formatDate(i.due_at)}`}>⏰ 기한 초과</span>}
                  {i.recheck_due_at && <RecheckTag note={i.recheck_note ?? ""} due={i.recheck_due_at} />}
                </td>
                {isAdmin && <td className="whitespace-nowrap px-3 py-3 text-slate-600">{i.assigned_to?.display_name ?? "-"}</td>}
                <td className="whitespace-nowrap px-3 py-3 text-slate-500">{formatDate(i.created_at)}</td>
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

/** 확인 후 다시 안내할 문의 표시 (기한이 지나면 빨간색) */
function RecheckTag({ note, due }: { note: string; due: string }) {
  const late = new Date(due).getTime() <= Date.now();
  return (
    <span className={`ml-1 text-xs font-semibold ${late ? "text-rose-700" : "text-blue-700"}`}
      title={`확인할 내용: ${note} · 다시 안내 기한 ${formatDate(due)}`}>
      🔁 {late ? "다시 안내 기한 지남" : `다시 안내 ${formatDate(due)}`}
    </span>
  );
}
