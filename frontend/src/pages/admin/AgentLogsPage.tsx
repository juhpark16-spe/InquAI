// AI 실행 로그 (/admin/agent-logs): 문의마다 에이전트가 무엇을 판단했고 어떤 도구를 썼는지, 성공했는지
// 관리자는 전체, 상담원은 자신에게 배정된 문의만 봅니다. 줄을 누르면 처리 경로·근거 FAQ·답변·도구 원본이 펼쳐집니다.
import { Fragment, useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import { Alert, Badge, Button, Select, Spinner, cx, formatDate } from "../../components/ui";
import { agentLogApi, errorMessage, kstDate, type AgentLogFilters } from "../../services/api";
import { DECISIONS, type AgentLogPage, type AgentLogRow } from "../../services/types";

const TOOLS = ["FAQ 검색", "배송 조회", "티켓 접수", "상담원 이관"];
const PERIODS: Record<string, number | null> = { "오늘": 1, "최근 7일": 7, "최근 30일": 30, "전체": null };
const SIZE = 30;
const sec = (ms: number | null | undefined) => (ms === null || ms === undefined ? "-" : `${(ms / 1000).toFixed(1)}초`);

function Stat({ label, value, sub, warn }: { label: string; value: ReactNode; sub?: ReactNode; warn?: boolean }) {
  return (
    <div className="rounded-2xl border border-hairline bg-white px-4 py-3">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx("mt-1 text-xl font-semibold tabular-nums", warn ? "text-rose-600" : "text-ink")}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

function Summary({ s }: { s: AgentLogPage["summary"] }) {
  const pct = (n: number) => (s.count ? `${Math.round((n / s.count) * 100)}%` : "-");
  const problems = s.errors + s.tool_failures + s.low_confidence;
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="실행 수" value={s.count} sub={`LLM 판단 ${s.by_decided_by.LLM ?? 0} · 규칙 판단 ${s.by_decided_by["규칙"] ?? 0}`} />
        <Stat label="자동 답변 비율" value={pct(s.by_decision["자동 답변"] ?? 0)}
          sub={`초안 ${s.by_decision["답변 초안"] ?? 0} · 담당자 연결 ${s.by_decision["담당자 연결"] ?? 0}`} />
        <Stat label="처리 시간 (LLM 판단)" value={sec(s.avg_latency_ms)} sub={`최대 ${sec(s.max_latency_ms)}`} />
        <Stat label="확인이 필요한 실행" value={problems} warn={problems > 0}
          sub={`오류 ${s.errors} · 도구 실패 ${s.tool_failures} · 확신도 0.8 미만 ${s.low_confidence}`} />
      </div>
      {Object.keys(s.by_tool).length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          <span className="py-1 text-muted">도구별</span>
          {Object.entries(s.by_tool).map(([tool, t]) => (
            <span key={tool} className="rounded-full border border-hairline bg-white px-3 py-1 text-body">
              {tool} <b className="tabular-nums text-ink">{t.count}</b>
              {t.failed > 0 && <span className="ml-1 text-rose-600">실패 {t.failed}</span>}
            </span>
          ))}
          <span className="py-1 text-muted">· 토큰 입력 {s.tokens.input.toLocaleString()} / 출력 {s.tokens.output.toLocaleString()} ({s.tokens.calls}회 호출)</span>
        </div>
      )}
    </div>
  );
}

function Detail({ log, titles }: { log: AgentLogRow; titles: Record<string, string> }) {
  const row = (label: string, children: ReactNode) => (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 text-slate-800">{children}</dd>
    </>
  );
  return (
    <dl className="grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-2 text-sm">
      {row("처리 경로", log.steps?.length ? log.steps.join(" → ") : "-")}
      {row("판단 이유", log.reason ?? "-")}
      {row("검색된 FAQ", log.retrieved_faqs.length ? (
        <ul className="space-y-0.5">
          {log.retrieved_faqs.map(([code, score]) => (
            <li key={code} className="text-xs">
              <span className="font-mono">{code}</span> {titles[code] ?? ""}{" "}
              <span className="text-slate-400">유사도 {Number(score).toFixed(2)}</span>
              {log.used_faq_ids.includes(code) && <span className="ml-1 rounded bg-emerald-100 px-1.5 text-emerald-700">답변 근거</span>}
            </li>
          ))}
        </ul>
      ) : "-")}
      {log.response_text && row(log.decision === "자동 답변" ? "고객에게 보낸 답" : "AI가 쓴 답 (상담원 검토용)", <p className="whitespace-pre-line rounded-lg bg-slate-50 p-2 text-xs">{log.response_text}</p>)}
      {row("LLM", log.llm_model ?? "사용 안 함 (규칙 판단)")}
      {row("토큰", log.tokens?.calls ? `입력 ${log.tokens.input} · 출력 ${log.tokens.output} (${log.tokens.calls}회)` : "-")}
      {log.error && row("오류", <span className="break-all text-rose-700">{log.error}</span>)}
      {row("도구 원본", log.tool_output
        ? <pre className="max-h-48 overflow-auto rounded-lg bg-slate-50 p-2 text-xs">{JSON.stringify(log.tool_output, null, 2)}</pre> : "-")}
      {log.trace_url && row("추적", (
        <a href={log.trace_url} target="_blank" rel="noreferrer" className="text-primary hover:underline">LangSmith에서 단계별로 보기 ↗</a>
      ))}
    </dl>
  );
}

function Flags({ log }: { log: AgentLogRow }) {
  const flags = [
    log.error && "오류",
    log.tool_success === false && "도구 실패",
    log.confidence < 0.8 && "확신도 낮음",
  ].filter(Boolean) as string[];
  if (!flags.length) return null;
  return <>{flags.map((f) => <span key={f} className="ml-1 rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-700">{f}</span>)}</>;
}

export default function AgentLogsPage() {
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<AgentLogPage | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<number | null>(null);

  const period = params.get("period") ?? "최근 7일";
  const page = Number(params.get("page") ?? 1);
  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next, { replace: true });
  };

  const load = useCallback(() => {
    const days = PERIODS[period] ?? null;
    const filters: AgentLogFilters = {
      decision: params.get("decision") || undefined, selected_tool: params.get("tool") || undefined,
      decided_by: params.get("by") || undefined, problem: params.get("problem") || undefined,
      inquiry_id: params.get("inquiry") ? Number(params.get("inquiry")) : undefined,
      ...(days ? { from: kstDate(days - 1), to: kstDate(0) } : {}), page, size: SIZE,
    };
    setError("");
    agentLogApi.list(filters).then(setData).catch((err) => setError(errorMessage(err)));
  }, [params, period, page]);
  useEffect(load, [load]);

  const pages = data ? Math.max(1, Math.ceil(data.total / SIZE)) : 1;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">AI 실행 로그</h1>
        <p className="text-sm text-slate-500">
          문의마다 AI가 고른 처리 방식, 사용한 도구와 성공 여부, 근거 FAQ, 처리 시간을 봅니다. 줄을 누르면 자세한 기록이 펼쳐집니다.
          {user?.role !== "admin" && " 상담원은 자신에게 배정된 문의만 보입니다."}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select aria-label="기간" value={period} onChange={(e) => set("period", e.target.value)}>
          {Object.keys(PERIODS).map((p) => <option key={p}>{p}</option>)}
        </Select>
        <Select aria-label="처리 방식" value={params.get("decision") ?? ""} onChange={(e) => set("decision", e.target.value)}>
          <option value="">처리 방식 전체</option>
          {DECISIONS.map((d) => <option key={d}>{d}</option>)}
        </Select>
        <Select aria-label="도구" value={params.get("tool") ?? ""} onChange={(e) => set("tool", e.target.value)}>
          <option value="">도구 전체</option>
          {TOOLS.map((t) => <option key={t}>{t}</option>)}
        </Select>
        <Select aria-label="판단 주체" value={params.get("by") ?? ""} onChange={(e) => set("by", e.target.value)}>
          <option value="">판단 전체</option>
          <option value="LLM">LLM 판단</option>
          <option value="규칙">규칙 판단</option>
        </Select>
        <label className="flex items-center gap-2 rounded-xl border border-hairline bg-white px-3 py-2.5 text-sm text-body">
          <input type="checkbox" checked={params.get("problem") === "true"} onChange={(e) => set("problem", e.target.checked ? "true" : "")} />
          확인이 필요한 것만
        </label>
        {params.get("inquiry") && (
          <Button variant="ghost" onClick={() => set("inquiry", "")}>문의 #{params.get("inquiry")} 필터 해제</Button>
        )}
      </div>

      {error && <Alert>{error}</Alert>}
      {data && <Summary s={data.summary} />}

      <div className="overflow-x-auto rounded-2xl border border-hairline bg-white">
        <table className="w-full min-w-[56rem] text-left text-sm">
          <thead className="border-b border-hairline bg-surface-card text-xs text-muted">
            <tr>{["시각", "문의", "유형 · 확신도", "처리 방식", "도구", "처리 시간"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-hairline">
            {data?.items.map((log) => (
              <Fragment key={log.id}>
                <tr className={cx("cursor-pointer align-top hover:bg-surface-card/60", open === log.id && "bg-surface-card/60")}
                  onClick={() => setOpen(open === log.id ? null : log.id)} aria-expanded={open === log.id}>
                  <td className="whitespace-nowrap px-3 py-3 text-slate-500">{formatDate(log.created_at)}</td>
                  <td className="px-3 py-3">
                    <Link to={`/admin/inquiries/${log.inquiry_id}`} onClick={(e) => e.stopPropagation()}
                      className="font-mono text-xs text-primary hover:underline">{log.inquiry_number}</Link>
                    <div className="max-w-64 truncate text-ink" title={log.inquiry_title}>{log.inquiry_title}</div>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3">
                    {log.category}{" "}
                    <span className={cx("tabular-nums", log.confidence < 0.8 ? "font-semibold text-amber-700" : "text-slate-500")}>
                      {Math.round(log.confidence * 100)}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-3">
                    <Badge value={log.decision} /> <span className="text-xs text-slate-500">{log.decided_by}</span>
                  </td>
                  <td className="px-3 py-3">
                    <span className="whitespace-nowrap">{log.selected_tool ?? "-"}</span>
                    {log.tool_success === true && <span className="ml-1 text-xs text-emerald-700">성공</span>}
                    <Flags log={log} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-3 tabular-nums text-slate-600">{log.decided_by === "규칙" ? "규칙 (즉시)" : sec(log.latency_ms)}</td>
                </tr>
                {open === log.id && (
                  <tr className="bg-surface-card/40">
                    <td colSpan={6} className="px-5 py-4"><Detail log={log} titles={data.faq_titles} /></td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {!data && !error && <p className="p-6 text-center text-slate-500"><Spinner /></p>}
        {data && data.items.length === 0 && <p className="p-6 text-center text-sm text-slate-500">조건에 맞는 실행 기록이 없습니다.</p>}
        {data && data.total > SIZE && (
          <div className="flex items-center justify-between border-t border-hairline px-4 py-2 text-sm">
            <span className="text-slate-500">총 {data.total}건 · {page}/{pages}쪽</span>
            <div className="flex gap-2">
              <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={page <= 1} onClick={() => set("page", String(page - 1))}>이전</Button>
              <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={page >= pages} onClick={() => set("page", String(page + 1))}>다음</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
