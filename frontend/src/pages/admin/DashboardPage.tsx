// 관리자 대시보드 (/admin): 지금 처리할 일, 기간 지표, 날짜별 유형·처리 현황, 처리 방식, AI 성능, 상담원별 미처리
// 색: 유형 8개는 고정 순서의 범주 색(유형마다 항상 같은 색), 긴급은 상태색(빨강) + 아이콘·글자로 표시
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { Alert, Card, Spinner, cx } from "../../components/ui";
import { errorMessage, statsApi, type StatsSummary } from "../../services/api";
import { CATEGORIES } from "../../services/types";

// 범주 색 8개 (색약 구분 검증된 순서, 유형 순서와 1:1로 고정)
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const CATEGORY_COLOR = Object.fromEntries(CATEGORIES.map((c, i) => [c, SERIES[i]]));
const INK = { muted: "#898781", grid: "#e1e0d9", axis: "#c3c2b7" };
const CRITICAL = "#d03b3b";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${Math.round(v * 100)}%`);
const shortDate = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;

function Tile({ label, value, sub, to, tone }: { label: string; value: ReactNode; sub?: ReactNode; to?: string; tone?: "critical" }) {
  const body = (
    <div className={cx("h-full rounded-xl border bg-white p-4 shadow-sm transition",
      tone === "critical" ? "border-rose-200" : "border-slate-200", to && "hover:border-indigo-300 hover:shadow")}>
      <p className={cx("text-xs font-medium", tone === "critical" ? "text-rose-700" : "text-slate-500")}>
        {tone === "critical" && <span aria-hidden>⚠ </span>}{label}
      </p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
  return to ? <Link to={to} className="block h-full">{body}</Link> : body;
}

/** 가로 막대 한 줄: 처리 방식·긴급도 비율처럼 항목이 적은 단일 계열 */
function HBar({ items, color, total }: { items: [string, number][]; color: string | ((k: string) => string); total: number }) {
  return (
    <ul className="space-y-2">
      {items.map(([label, n]) => (
        <li key={label} className="grid grid-cols-[5.5rem_1fr_4.5rem] items-center gap-2 text-sm" title={`${label}: ${n}건`}>
          <span className="truncate text-slate-600">{label}</span>
          <div className="h-2.5 rounded-full bg-slate-100">
            <div className="h-2.5 rounded-full" style={{ width: `${total ? (n / total) * 100 : 0}%`,
              background: typeof color === "string" ? color : color(label) }} />
          </div>
          <span className="text-right tabular-nums text-slate-700">{n}건 <span className="text-xs text-slate-400">{pct(total ? n / total : null)}</span></span>
        </li>
      ))}
    </ul>
  );
}

/** 범례: Recharts 기본 범례는 이름순으로 정렬돼 색 순서와 어긋나서, 정해진 순서대로 직접 그림 */
function LegendRow({ items }: { items: [string, string][] }) {
  return (
    <ul className="mt-2 flex flex-wrap justify-center gap-x-3 gap-y-1 text-xs text-slate-600">
      {items.map(([name, color]) => (
        <li key={name} className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: color }} />{name}
        </li>
      ))}
    </ul>
  );
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const rows = payload.filter((p) => p.value > 0);
  const total = payload.reduce((s, p) => s + (p.value || 0), 0);
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-semibold text-slate-900">{label} · 총 {total}건</p>
      {rows.length === 0 && <p className="text-slate-500">문의 없음</p>}
      {rows.map((p) => (
        <p key={p.name} className="flex items-center gap-2 text-slate-700">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color }} />{p.name}
          <span className="ml-auto pl-3 tabular-nums">{p.value}</span>
        </p>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<StatsSummary | null>(null);
  const [error, setError] = useState("");
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    setError("");
    statsApi.summary(days).then(setData).catch((err) => setError(errorMessage(err)));
  }, [days]);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <p className="p-6 text-center text-slate-500"><Spinner /></p>;

  const daily = data.daily.map((d) => ({ date: shortDate(d.date), ...d.by_category, 처리됨: d.done, 미처리: d.open }));
  const analyzed = Object.values(data.by_category).reduce((a, b) => a + b, 0);
  const axis = { stroke: INK.axis, tick: { fill: INK.muted, fontSize: 12 }, tickLine: false };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-900">대시보드</h1>
          <p className="text-sm text-slate-500">{data.range.from} ~ {data.range.to} (한국 시간)</p>
        </div>
        <div className="flex gap-1 rounded-lg border border-slate-200 bg-white p-1" role="group" aria-label="기간">
          {[7, 30].map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={cx("rounded-md px-3 py-1 text-sm", days === d ? "bg-indigo-600 text-white" : "text-slate-600 hover:bg-slate-50")}>
              최근 {d}일
            </button>
          ))}
        </div>
      </div>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">지금 처리할 일 <span className="font-normal text-slate-400">(기간과 관계없이 현재)</span></h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile label="긴급 미처리" value={data.now.urgent_open} sub="긴급도 높음 · 아직 처리 안 됨" tone={data.now.urgent_open ? "critical" : undefined}
            to="/admin/inquiries?open=true&urgency=높음" />
          <Tile label="미처리 전체" value={data.now.open} sub="접수 · 검토 대기 · 담당자 처리" to="/admin/inquiries?open=true" />
          <Tile label="검토 대기" value={data.now.review_waiting} sub="AI 초안을 사람이 확인해야 함" to="/admin/inquiries?status=검토 대기" />
          <Tile label="미배정" value={data.now.unassigned_open} sub="담당자가 정해지지 않은 미처리" to="/admin/inquiries?open=true&assigned_to=none" />
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">기간 지표</h2>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile label="문의 수" value={`${data.kpi.total}건`} sub={data.kpi.today !== null ? `오늘 ${data.kpi.today}건` : undefined} />
          <Tile label="자동 처리율" value={pct(data.kpi.auto_rate)} sub="목표 30% 이상" />
          <Tile label="초안 무수정 승인율" value={pct(data.kpi.approval_without_edit_rate)} sub="목표 70% 이상 (승인 기능 3주차)" />
          <Tile label="AI 평균 처리 시간" value={data.ai.avg_latency_ms !== null ? `${(data.ai.avg_latency_ms / 1000).toFixed(1)}초` : "-"} sub="LLM이 판단한 문의 기준, 목표 10초 이내" />
        </div>
      </section>

      <Card title={
        <span className="flex items-center justify-between">
          날짜별 문의 유형
          <button className="text-xs font-normal text-indigo-600 hover:underline" onClick={() => setShowTable(!showTable)}>
            {showTable ? "그래프로 보기" : "표로 보기"}
          </button>
        </span>}>
        {showTable ? (
          <div className="overflow-x-auto">
            <table className="w-full text-right text-xs tabular-nums">
              <thead className="text-slate-500">
                <tr><th className="py-1 text-left">날짜</th>{CATEGORIES.map((c) => <th key={c} className="px-2 py-1 font-medium">{c}</th>)}<th className="px-2">합계</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.daily.map((d) => (
                  <tr key={d.date}><td className="py-1 text-left">{d.date}</td>
                    {CATEGORIES.map((c) => <td key={c} className="px-2">{d.by_category[c]}</td>)}
                    <td className="px-2 font-medium">{d.total}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="h-72">
            <ResponsiveContainer>
              <BarChart data={daily} margin={{ top: 8, right: 8, left: -16, bottom: 0 }} barCategoryGap="30%">
                <CartesianGrid vertical={false} stroke={INK.grid} />
                <XAxis dataKey="date" {...axis} />
                <YAxis allowDecimals={false} {...axis} axisLine={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(11,11,11,0.04)" }} />
                {CATEGORIES.map((c) => (
                  <Bar key={c} dataKey={c} stackId="cat" fill={CATEGORY_COLOR[c]} stroke="#fff" strokeWidth={1} maxBarSize={40} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
        {!showTable && <LegendRow items={CATEGORIES.map((c) => [c, CATEGORY_COLOR[c]])} />}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="날짜별 처리 · 미처리">
          <div className="h-60">
            <ResponsiveContainer>
              <BarChart data={daily} margin={{ top: 8, right: 8, left: -16, bottom: 0 }} barCategoryGap="30%">
                <CartesianGrid vertical={false} stroke={INK.grid} />
                <XAxis dataKey="date" {...axis} />
                <YAxis allowDecimals={false} {...axis} axisLine={false} />
                <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(11,11,11,0.04)" }} />
                <Bar dataKey="처리됨" stackId="s" fill={SERIES[0]} stroke="#fff" strokeWidth={1} maxBarSize={40} />
                <Bar dataKey="미처리" stackId="s" fill={SERIES[1]} stroke="#fff" strokeWidth={1} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <LegendRow items={[["처리됨", SERIES[0]], ["미처리", SERIES[1]]]} />
          <p className="mt-2 text-xs text-slate-500">처리됨 = 자동 처리 + 완료, 미처리 = 접수 · 검토 대기 · 담당자 처리</p>
        </Card>

        <Card title="처리 방식 · 긴급도">
          <p className="mb-2 text-xs font-medium text-slate-500">처리 방식 (분석된 {analyzed}건)</p>
          <HBar items={Object.entries(data.by_decision)} color={SERIES[0]} total={analyzed} />
          <p className="mb-2 mt-5 text-xs font-medium text-slate-500">긴급도</p>
          <HBar items={Object.entries(data.by_urgency)} total={analyzed}
            color={(k) => (k === "높음" ? CRITICAL : k === "보통" ? "#9ec5f4" : "#cde2fb")} />
          <p className="mt-4 text-xs text-slate-500">
            판단 주체: 규칙 {data.by_decided_by["규칙"]}건 · LLM {data.by_decided_by["LLM"]}건
          </p>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="AI 처리 현황">
          <dl className="grid grid-cols-2 gap-y-3 text-sm">
            <dt className="text-slate-500">확신도 0.8 미만 → 담당자 연결</dt><dd className="text-right tabular-nums">{data.ai.low_confidence}건</dd>
            <dt className="text-slate-500">LLM 오류·시간 초과</dt><dd className="text-right tabular-nums">{data.ai.errors}건</dd>
            <dt className="text-slate-500">LLM 호출</dt><dd className="text-right tabular-nums">{data.ai.llm_calls}회</dd>
            <dt className="text-slate-500">토큰 (입력 / 출력)</dt>
            <dd className="text-right tabular-nums">{data.ai.tokens.input.toLocaleString()} / {data.ai.tokens.output.toLocaleString()}</dd>
          </dl>
        </Card>

        <Card title="담당자별 미처리">
          <table className="w-full text-sm">
            <thead className="text-xs text-slate-500">
              <tr><th className="pb-1 text-left font-medium">담당자</th><th className="pb-1 text-right font-medium">미처리</th><th className="pb-1 text-right font-medium">긴급</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.staff.map((s) => (
                <tr key={s.id}>
                  <td className="py-1.5">{s.display_name} <span className="text-xs text-slate-400">{s.role === "admin" ? "관리자" : "상담원"}</span></td>
                  <td className="py-1.5 text-right tabular-nums">{s.open}</td>
                  <td className={cx("py-1.5 text-right tabular-nums", s.urgent_open > 0 && "font-semibold text-rose-700")}>
                    {s.urgent_open > 0 && <span aria-hidden>⚠ </span>}{s.urgent_open}
                  </td>
                </tr>
              ))}
              <tr>
                <td className="py-1.5 text-slate-500">미배정</td>
                <td className="py-1.5 text-right tabular-nums">
                  <Link to="/admin/inquiries?open=true&assigned_to=none" className="text-indigo-600 hover:underline">{data.now.unassigned_open}</Link>
                </td>
                <td />
              </tr>
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  );
}
