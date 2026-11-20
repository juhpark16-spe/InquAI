// 작업 기록 (/admin/audit, 관리자): 누가 · 언제 · 무엇을 했는지 (로그인·로그인 실패·계정·배정·답변 발송·FAQ·답변 문구)
// 읽기 전용. 기록은 서버의 각 작업이 남기며 고치거나 지울 수 없음 (backend/api/audit_logs.py)
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";

import { Alert, Button, Select, Spinner, cx, formatDate } from "../../components/ui";
import { auditApi, errorMessage, inquiryApi, type AuditItem } from "../../services/api";
import type { User } from "../../services/types";

const SIZE = 30;
// 묶음별 색: 로그인·보안만 눈에 띄게, 나머지는 회색 계열 (색의 뜻: DESIGN.md)
const GROUP_STYLE: Record<string, string> = {
  "로그인·보안": "bg-sky-50 text-sky-800", 계정: "bg-indigo-50 text-indigo-800", "문의 처리": "bg-slate-100 text-slate-700",
  답변: "bg-slate-100 text-slate-700", 설정: "bg-amber-50 text-amber-800",
};

export default function AuditLogPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<Awaited<ReturnType<typeof auditApi.list>> | null>(null);
  const [staff, setStaff] = useState<User[]>([]);
  const [error, setError] = useState("");
  const group = params.get("group") ?? "";
  const actor = params.get("actor") ?? "";
  const days = Number(params.get("days") ?? 7);
  const page = Number(params.get("page") ?? 1);

  useEffect(() => { inquiryApi.staff().then(setStaff).catch(() => setStaff([])); }, []);
  useEffect(() => {
    setError("");
    auditApi.list({ group, actor, days, page }).then(setData).catch((err) => setError(errorMessage(err)));
  }, [group, actor, days, page]);

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  };
  const lastPage = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">작업 기록</h1>
        <p className="mt-1 text-sm text-muted">
          누가 언제 무엇을 했는지 남는 기록입니다 (로그인·로그인 실패, 계정 변경, 배정, 답변 발송, FAQ·답변 문구 변경).
          고치거나 지울 수 없고, 비밀번호 같은 비밀값은 남기지 않습니다.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select value={group} onChange={(e) => update("group", e.target.value)} aria-label="종류">
          <option value="">모든 종류</option>
          {(data?.groups ?? ["로그인·보안", "계정", "문의 처리", "답변", "설정"]).map((g) => <option key={g} value={g}>{g}</option>)}
        </Select>
        <Select value={actor} onChange={(e) => update("actor", e.target.value)} aria-label="누가">
          <option value="">모든 사람</option>
          {staff.map((s) => <option key={s.id} value={String(s.id)}>{s.display_name}</option>)}
          <option value="system">시스템 (자동 배정 등)</option>
          <option value="unknown">알 수 없음 (없는 아이디로 로그인 시도)</option>
        </Select>
        <Select value={String(days)} onChange={(e) => update("days", e.target.value === "7" ? "" : e.target.value)} aria-label="기간">
          <option value="1">오늘 (24시간)</option>
          <option value="7">최근 7일</option>
          <option value="30">최근 30일</option>
          <option value="90">최근 90일</option>
        </Select>
        {(group || actor || params.get("days")) && <Button variant="ghost" onClick={() => setParams(new URLSearchParams())}>조건 초기화</Button>}
        {data && data.login_failed > 0 && (
          <button type="button" onClick={() => update("group", "로그인·보안")}
            className="ml-auto rounded-full bg-rose-50 px-3 py-1.5 text-sm font-semibold text-rose-700 hover:bg-rose-100">
            로그인 실패 {data.login_failed}건
          </button>
        )}
      </div>

      {error && <Alert>{error}</Alert>}

      <div className="overflow-x-auto rounded-2xl border border-hairline bg-white">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-hairline text-sm text-muted">
            <tr>{["시각", "누가", "무엇을", "대상", "내용", "IP"].map((h) => <th key={h} className="whitespace-nowrap px-3 py-3 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {data?.items.map((a: AuditItem) => (
              <tr key={a.id} className={cx(a.action === "login_failed" && "bg-rose-50/40")}>
                <td className="whitespace-nowrap px-3 py-2.5 text-muted">{formatDate(a.at)}</td>
                <td className="whitespace-nowrap px-3 py-2.5 text-ink">{a.actor.name}</td>
                <td className="whitespace-nowrap px-3 py-2.5">
                  <span className={cx("rounded-full px-2.5 py-0.5 text-xs font-medium",
                    a.action === "login_failed" ? "bg-rose-100 font-semibold text-rose-700" : GROUP_STYLE[a.group] ?? "bg-slate-100 text-slate-700")}>
                    {a.label}
                  </span>
                </td>
                <td className="whitespace-nowrap px-3 py-2.5">
                  {a.target ? (a.target.link ? <Link to={a.target.link} className="text-primary hover:underline">{a.target.label}</Link> : a.target.label) : "-"}
                </td>
                <td className="max-w-md truncate px-3 py-2.5 text-body" title={a.summary}>{a.summary || "-"}</td>
                <td className="whitespace-nowrap px-3 py-2.5 font-mono text-xs text-muted">{a.ip ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!data && !error && <p className="p-6 text-center text-muted"><Spinner /></p>}
        {data?.items.length === 0 && <p className="p-6 text-center text-sm text-muted">이 조건의 기록이 없습니다.</p>}
      </div>

      {data && (
        <div className="flex items-center justify-between text-sm text-muted">
          <span>총 {data.total.toLocaleString()}건 · 최근 {data.range_days}일</span>
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
