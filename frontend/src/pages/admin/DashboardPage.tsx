// 관리자 대시보드 (/admin): 지금 처리할 일 → 기간 지표(지난 기간 대비) → 날짜별 유형 + 최근 활동
// → 처리·미처리, 처리 방식·긴급도 → AI 현황, 담당자별 미처리 → 문의가 많은 상품 (상세페이지 개선 신호)
// 색: 카드는 흰 바탕, 위험한 값(기한 초과·긴급)만 빨강. 유형 8개는 고정 순서의 범주 색(유형마다 항상 같은 색)
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useAuth } from "../../auth/AuthProvider";
import Icon, { type IconName } from "../../components/Icon";
import { Alert, Spinner, cx, initialOf } from "../../components/ui";
import { errorMessage, statsApi, type ActivityItem, type ProductStats, type StatsSummary } from "../../services/api";
import { CATEGORIES } from "../../services/types";

// 범주 색 8개 (색약 구분 검증된 순서, 유형 순서와 1:1로 고정)
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const CATEGORY_COLOR = Object.fromEntries(CATEGORIES.map((c, i) => [c, SERIES[i]]));
const INK = { muted: "#6a6a6a", grid: "#ebe6d6", axis: "#d9d2c0" };
const CRITICAL = "#d03b3b";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${Math.round(v * 100)}%`);
const shortDate = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;

function ago(iso: string) {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  if (min < 60 * 24) return `${Math.floor(min / 60)}시간 전`;
  return `${Math.floor(min / 60 / 24)}일 전`;
}

/** 흰 카드 + 머리글(아이콘 상자, 제목, 설명, 오른쪽 버튼) */
function Panel({ icon, title, sub, action, children, className }: {
  icon?: IconName; title: ReactNode; sub?: ReactNode; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={cx("rounded-2xl border border-hairline bg-white", className)}>
      <header className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
        <div className="flex items-center gap-3">
          {icon && (
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-card text-ink">
              <Icon name={icon} />
            </span>
          )}
          <div>
            <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
            {sub && <p className="text-xs text-muted">{sub}</p>}
          </div>
        </div>
        {action}
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}

/** 지금 처리할 일 카드: 값이 있고 위험하면 빨강 */
function WorkCard({ icon, label, value, sub, to, critical }: {
  icon: IconName; label: string; value: number; sub: string; to: string; critical?: boolean;
}) {
  const alarm = critical && value > 0;
  return (
    <Link to={to} className={cx("group block rounded-2xl border bg-white p-4 transition hover:-translate-y-0.5",
      alarm ? "border-rose-200" : "border-hairline")}>
      <div className="flex items-start justify-between">
        <p className={cx("text-sm", alarm ? "font-semibold text-rose-700" : "text-muted")}>{label}</p>
        <span className={cx("flex h-8 w-8 items-center justify-center rounded-lg",
          alarm ? "bg-rose-50 text-rose-600" : "bg-surface-card text-ink")}>
          <Icon name={icon} />
        </span>
      </div>
      <p className={cx("display mt-1 text-4xl tabular-nums", alarm && "!text-rose-700")}>{value}</p>
      <p className="mt-1 flex items-center justify-between gap-2 text-xs text-muted">
        <span>{sub}</span>
        <Icon name="arrow" className="h-3.5 w-3.5 shrink-0 opacity-0 transition group-hover:opacity-100" />
      </p>
    </Link>
  );
}

/** 증감 표시: 좋아진 방향이면 초록, 나빠지면 빨강 */
function Delta({ value, unit, goodWhenUp = true }: { value: number | null; unit: "%" | "%p"; goodWhenUp?: boolean }) {
  if (value === null || !Number.isFinite(value)) return <span className="text-xs text-muted">비교 없음</span>;
  const rounded = Math.round(value * 10) / 10;
  if (rounded === 0) return <span className="text-xs font-semibold text-muted">변화 없음</span>;
  const up = rounded > 0;
  const good = up === goodWhenUp;
  return (
    <span className={cx("inline-flex items-center gap-0.5 text-xs font-semibold", good ? "text-emerald-700" : "text-rose-700")}>
      <Icon name={up ? "up" : "down"} className="h-3.5 w-3.5" />
      {up ? "+" : ""}{rounded}{unit}
    </span>
  );
}

/** 작은 막대 (날짜별 흐름, 마지막 날 = 진하게) */
function Spark({ values }: { values: number[] }) {
  const max = Math.max(...values, 1);
  return (
    <div className="flex h-8 items-end gap-[3px]" aria-hidden>
      {values.map((v, i) => (
        <span key={i} className={cx("w-1.5 rounded-sm", i === values.length - 1 ? "bg-primary" : "bg-indigo-200")}
          style={{ height: `${Math.max(12, (v / max) * 100)}%` }} />
      ))}
    </div>
  );
}

function Kpi({ label, value, delta, compare, spark }: { label: string; value: ReactNode; delta: ReactNode; compare: ReactNode; spark?: number[] }) {
  return (
    <div className="p-5">
      <p className="text-sm text-muted">{label}</p>
      <div className="mt-1 flex items-end justify-between gap-3">
        <div>
          <p className="flex items-baseline gap-2">
            <span className="display text-3xl tabular-nums">{value}</span>
            {delta}
          </p>
          <p className="mt-1 text-xs text-muted">{compare}</p>
        </div>
        {spark && spark.length > 1 && <Spark values={spark.slice(-10)} />}
      </div>
    </div>
  );
}

/** 얇은 가로 막대 목록: 점 + 이름 + 건수·비율, 아래에 막대 */
function ShareBars({ items, color, total }: { items: [string, number][]; color: (k: string) => string; total: number }) {
  return (
    <ul className="space-y-3.5">
      {items.map(([label, n]) => (
        <li key={label} title={`${label}: ${n}건`}>
          <div className="mb-1.5 flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-body">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: color(label) }} />{label}
            </span>
            <span className="tabular-nums text-ink">{n}건 <span className="text-xs text-muted">{pct(total ? n / total : null)}</span></span>
          </div>
          <div className="h-1.5 rounded-full bg-surface-card">
            <div className="h-1.5 rounded-full" style={{ width: `${total ? (n / total) * 100 : 0}%`, background: color(label) }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** 문의가 많은 상품: 유형 비율 막대 + 가장 많은 유형에 맞춘 상세페이지 개선 힌트 (채널톡 '주문 연동 상담' 벤치마킹) */
function Products({ data }: { data: ProductStats | null }) {
  if (!data) return <p className="text-center text-muted"><Spinner /></p>;
  if (data.items.length === 0) return <p className="text-sm text-muted">이 기간에 주문과 연결된 문의가 없습니다.</p>;
  const max = data.items[0].count;
  return (
    <ul className="space-y-4">
      {data.items.map((p, rank) => (
        <li key={p.product}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="min-w-0 truncate font-semibold text-ink"><span className="mr-1.5 text-muted">{rank + 1}</span>{p.product}</span>
            <span className="shrink-0 tabular-nums text-ink">{p.count}건
              <span className="ml-1.5 text-xs text-muted">자동 답변 {p.auto} · 부정 {p.negative}</span>
            </span>
          </div>
          <div className="mt-1.5 flex h-2 overflow-hidden rounded-full bg-surface-card" style={{ width: `${(p.count / max) * 100}%` }}
            title={Object.entries(p.by_category).map(([c, n]) => `${c} ${n}`).join(" · ")}>
            {Object.entries(p.by_category).map(([c, n]) => (
              <span key={c} style={{ width: `${(n / p.count) * 100}%`, background: CATEGORY_COLOR[c] }} />
            ))}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-muted">
            {Object.entries(p.by_category).map(([c, n]) => (
              <span key={c} className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm" style={{ background: CATEGORY_COLOR[c] }} />{c} {n}</span>
            ))}
          </div>
          {p.hint && <p className="mt-1.5 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-900">💡 {p.hint}</p>}
          <p className="mt-1 truncate text-xs text-muted">
            {p.examples.map((e, k) => (
              <span key={e.inquiry_id}>{k > 0 && " · "}<Link to={`/admin/inquiries/${e.inquiry_id}`} className="hover:underline">{e.title}</Link></span>
            ))}
          </p>
        </li>
      ))}
    </ul>
  );
}

/** 범례: Recharts 기본 범례는 이름순으로 정렬돼 색 순서와 어긋나서, 정해진 순서대로 직접 그림 */
function LegendRow({ items }: { items: [string, string][] }) {
  return (
    <ul className="mt-2 flex flex-wrap justify-center gap-x-3 gap-y-1 text-xs text-body">
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
    <div className="rounded-xl border border-hairline bg-white px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-semibold text-ink">{label} · 총 {total}건</p>
      {rows.length === 0 && <p className="text-muted">문의 없음</p>}
      {rows.map((p) => (
        <p key={p.name} className="flex items-center gap-2 text-body">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: p.color }} />{p.name}
          <span className="ml-auto pl-3 tabular-nums">{p.value}</span>
        </p>
      ))}
    </div>
  );
}

const ACTIVITY_ICON: Record<ActivityItem["kind"], IconName> = {
  received: "inbox", followup: "message", ai: "bot", assign: "swap", status: "check", draft: "message", sent: "send",
  correct: "eye",
};

function Activity({ items }: { items: ActivityItem[] | null }) {
  if (!items) return <p className="py-6 text-center text-muted"><Spinner /></p>;
  if (!items.length) return <p className="py-6 text-center text-sm text-muted">아직 활동이 없습니다.</p>;
  return (
    <ol className="relative space-y-4 before:absolute before:bottom-2 before:left-[13px] before:top-2 before:w-px before:bg-hairline">
      {items.map((e, i) => (
        <li key={i} className="relative flex gap-3">
          <span className={cx("z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border bg-white",
            e.kind === "ai" ? "border-brand-lavender text-[#5b45b0]" : e.kind === "sent" ? "border-brand-mint text-brand-teal" : "border-hairline text-body")}>
            <Icon name={ACTIVITY_ICON[e.kind]} className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0 text-sm">
            <p className="text-ink"><b className="font-semibold">{e.actor}</b> · {e.text}</p>
            <p className="truncate text-xs text-muted">
              <Link to={`/admin/inquiries/${e.inquiry_id}`} className="hover:text-ink hover:underline">{e.title}</Link>
              {" · "}{ago(e.at)}
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<StatsSummary | null>(null);
  const [activity, setActivity] = useState<ActivityItem[] | null>(null);
  const [error, setError] = useState("");
  const [showTable, setShowTable] = useState(false);
  const [products, setProducts] = useState<ProductStats | null>(null);

  useEffect(() => {
    setError("");
    statsApi.summary(days).then(setData).catch((err) => setError(errorMessage(err)));
    statsApi.products(Math.max(days, 30)).then(setProducts).catch(() => setProducts(null));  // 상품별은 최소 30일 (건수가 적어서)
  }, [days]);
  useEffect(() => {
    statsApi.activity(8).then(setActivity).catch(() => setActivity([]));
  }, []);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <p className="p-6 text-center text-muted"><Spinner /></p>;

  const daily = data.daily.map((d) => ({ date: shortDate(d.date), ...d.by_category, 처리됨: d.done, 미처리: d.open }));
  const analyzed = Object.values(data.by_category).reduce((a, b) => a + b, 0);
  const axis = { stroke: INK.axis, tick: { fill: INK.muted, fontSize: 12 }, tickLine: false };
  const prev = data.previous;
  const change = (cur: number | null, before: number | null) =>
    cur === null || before === null || before === 0 ? null : ((cur - before) / before) * 100;
  const points = (cur: number | null, before: number | null) => (cur === null || before === null ? null : (cur - before) * 100);
  const sec = (ms: number | null) => (ms === null ? "-" : `${(ms / 1000).toFixed(1)}초`);
  const hour = new Date().getHours();
  const hello = hour < 12 ? "좋은 아침이에요" : hour < 18 ? "안녕하세요" : "오늘도 수고 많으셨어요";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="display text-3xl sm:text-4xl">{hello}, {user?.display_name}님</h1>
          <p className="mt-1 text-sm text-muted">지금 쌓인 문의와 최근 {days}일 현황입니다 · {data.range.from} ~ {data.range.to} (한국 시간)</p>
        </div>
        <div className="flex gap-1 rounded-xl border border-hairline bg-white p-1" role="group" aria-label="기간">
          {[7, 14, 30].map((d) => (
            <button key={d} onClick={() => setDays(d)} aria-pressed={days === d}
              className={cx("rounded-lg px-3 py-1.5 text-sm", days === d ? "bg-primary font-semibold text-white" : "text-body hover:bg-surface-card")}>
              {d}일
            </button>
          ))}
        </div>
      </div>

      <section>
        <h2 className="mb-3 text-[15px] font-semibold text-ink">지금 처리할 일 <span className="font-normal text-muted">· 기간과 관계없이 현재</span></h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          <WorkCard icon="clock" label="답변 기한 초과" value={data.now.overdue_open} sub="긴급 4시간 · 그 외 24시간"
            to="/admin/inquiries?overdue=true" critical />
          <WorkCard icon="alert" label="긴급 미처리" value={data.now.urgent_open} sub="긴급도 높음"
            to="/admin/inquiries?open=true&urgency=높음" critical />
          <WorkCard icon="inbox" label="미처리 전체" value={data.now.open} sub="접수·검토 대기·담당자 처리" to="/admin/inquiries?open=true" />
          <WorkCard icon="eye" label="검토 대기" value={data.now.review_waiting} sub="AI 초안 확인 필요" to="/admin/inquiries?status=검토 대기" />
          <WorkCard icon="userX" label="미배정" value={data.now.unassigned_open} sub="담당자 없음" to="/admin/inquiries?open=true&assigned_to=none" />
        </div>
      </section>

      {/* 기간 지표: 한 카드 안에 구분선으로 4칸 */}
      <section className="grid divide-y divide-hairline rounded-2xl border border-hairline bg-white sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-4 xl:divide-x">
        <Kpi label="문의 수" value={`${data.kpi.total}건`}
          delta={<Delta value={change(data.kpi.total, prev.total)} unit="%" goodWhenUp={false} />}
          compare={`지난 ${days}일 ${prev.total}건${data.kpi.today !== null ? ` · 오늘 ${data.kpi.today}건` : ""}`}
          spark={data.daily.map((d) => d.total)} />
        <Kpi label="자동 처리율" value={pct(data.kpi.auto_rate)}
          delta={<Delta value={points(data.kpi.auto_rate, prev.auto_rate)} unit="%p" />}
          compare={`지난 ${days}일 ${pct(prev.auto_rate)} · 목표 30% 이상`}
          spark={data.daily.map((d) => (d.total ? d.auto / d.total : 0))} />
        <Kpi label="초안 무수정 승인율" value={pct(data.kpi.approval_without_edit_rate)}
          delta={null} compare="AI 초안을 고치지 않고 보낸 비율 · 목표 70% 이상" />
        <Kpi label="AI 평균 처리 시간" value={sec(data.ai.avg_latency_ms)}
          delta={<Delta value={change(data.ai.avg_latency_ms, prev.avg_latency_ms)} unit="%" goodWhenUp={false} />}
          compare={`지난 ${days}일 ${sec(prev.avg_latency_ms)} · 목표 10초 이내`} />
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <Panel className="xl:col-span-2" icon="dashboard" title="날짜별 문의 유형" sub="유형마다 같은 색으로 쌓아 보여 줍니다"
          action={
            <button className="rounded-lg border border-hairline px-3 py-1.5 text-xs font-medium text-ink hover:bg-surface-card"
              onClick={() => setShowTable(!showTable)}>
              {showTable ? "그래프로 보기" : "표로 보기"}
            </button>}>
          {showTable ? (
            <div className="overflow-x-auto">
              <table className="w-full text-right text-xs tabular-nums">
                <thead className="text-muted">
                  <tr><th className="py-1 text-left">날짜</th>{CATEGORIES.map((c) => <th key={c} className="px-2 py-1 font-medium">{c}</th>)}<th className="px-2">합계</th></tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {data.daily.map((d) => (
                    <tr key={d.date}><td className="py-1 text-left">{d.date}</td>
                      {CATEGORIES.map((c) => <td key={c} className="px-2">{d.by_category[c]}</td>)}
                      <td className="px-2 font-medium">{d.total}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <>
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
              <LegendRow items={CATEGORIES.map((c) => [c, CATEGORY_COLOR[c]])} />
            </>
          )}
        </Panel>

        <Panel icon="clock" title="최근 활동" sub="AI 판단 · 배정 · 답변 발송">
          <Activity items={activity} />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel icon="check" title="날짜별 처리 · 미처리" sub="처리됨 = 자동 처리 + 완료">
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
        </Panel>

        <Panel icon="zap" title="처리 방식 · 긴급도" sub={`분석된 ${analyzed}건 · 판단 주체 규칙 ${data.by_decided_by["규칙"]}건 · LLM ${data.by_decided_by["LLM"]}건`}>
          <p className="mb-3 text-xs font-semibold tracking-wider text-muted">처리 방식</p>
          <ShareBars items={Object.entries(data.by_decision)} total={analyzed} color={() => SERIES[0]} />
          <p className="mb-3 mt-6 text-xs font-semibold tracking-wider text-muted">긴급도</p>
          <ShareBars items={Object.entries(data.by_urgency)} total={analyzed}
            color={(k) => (k === "높음" ? CRITICAL : k === "보통" ? "#9ec5f4" : "#cde2fb")} />
        </Panel>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel icon="bot" title="AI 처리 현황 · 고객 만족도" sub="고객이 남긴 '도움이 되었나요?' 평가 기준">
          <div className="mb-5 grid grid-cols-2 gap-3">
            {([["AI 자동 답변", data.ratings.ai], ["상담원 답변", data.ratings.agent]] as const).map(([name, r]) => (
              <div key={name} className="rounded-xl bg-surface-soft p-4">
                <p className="text-xs text-muted">{name} 만족도</p>
                <p className="display mt-1 text-2xl tabular-nums">{pct(r.satisfaction)}</p>
                <p className="text-xs text-muted">👍 {r.up} · 👎 {r.down}</p>
              </div>
            ))}
          </div>
          <dl className="grid grid-cols-2 gap-y-2.5 text-sm">
            <dt className="text-muted">확신도 0.8 미만 → 담당자 연결</dt><dd className="text-right tabular-nums text-ink">{data.ai.low_confidence}건</dd>
            <dt className="text-muted">LLM 오류·시간 초과</dt>
            <dd className={cx("text-right tabular-nums", data.ai.errors ? "font-semibold text-rose-700" : "text-ink")}>{data.ai.errors}건</dd>
            <dt className="text-muted" title="상담원이 고친 유형·감정. 재학습 데이터로 모읍니다">분류 수정 (재학습 데이터)</dt>
            <dd className="text-right tabular-nums text-ink">
              유형 {data.ai.corrections.category}건 · 감정 {data.ai.corrections.sentiment}건
            </dd>
            <dt className="text-muted">답변 초안 작성 실패</dt>
            <dd className={cx("text-right tabular-nums", data.ai.draft_failures ? "font-semibold text-amber-700" : "text-ink")}>{data.ai.draft_failures}건</dd>
            <dt className="text-muted">LLM 호출</dt><dd className="text-right tabular-nums text-ink">{data.ai.llm_calls}회</dd>
            <dt className="text-muted">토큰 (입력 / 출력)</dt>
            <dd className="text-right tabular-nums text-ink">{data.ai.tokens.input.toLocaleString()} / {data.ai.tokens.output.toLocaleString()}</dd>
          </dl>
        </Panel>

        <Panel icon="users" title="담당자별 미처리" sub="지금 맡고 있는 문의"
          action={<Link to="/admin/inquiries?open=true" className="flex items-center gap-1 text-xs font-medium text-ink hover:underline">전체 보기 <Icon name="arrow" className="h-3.5 w-3.5" /></Link>}>
          <ul className="divide-y divide-hairline">
            {data.staff.map((s) => (
              <li key={s.id} className="flex items-center gap-3 py-2.5 first:pt-0">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-hairline bg-surface-soft text-sm font-semibold text-ink" aria-hidden>
                  {initialOf(s.display_name)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ink">{s.display_name}</p>
                  <p className="text-xs text-muted">{s.role === "admin" ? "관리자" : "상담원"}</p>
                </div>
                {s.urgent_open > 0 && (
                  <span className="rounded-full bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700">긴급 {s.urgent_open}</span>
                )}
                <span className="w-14 text-right text-sm tabular-nums text-ink">{s.open}건</span>
              </li>
            ))}
            <li className="flex items-center gap-3 py-2.5 pb-0">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-dashed border-slate-300 text-muted" aria-hidden>
                <Icon name="userX" />
              </span>
              <p className="flex-1 text-sm text-muted">미배정</p>
              <Link to="/admin/inquiries?open=true&assigned_to=none" className="w-14 text-right text-sm tabular-nums text-ink hover:underline">
                {data.now.unassigned_open}건
              </Link>
            </li>
          </ul>
        </Panel>
      </div>

      <Panel icon="inbox" title="문의가 많은 상품" sub={products
        ? `최근 ${Math.max(days, 30)}일 · 주문과 연결된 문의 ${products.linked}건 (전체 ${products.total}건) · 같은 상품에 문의가 몰리면 상세페이지 개선 신호`
        : "주문과 연결된 문의"}>
        <Products data={products} />
      </Panel>
    </div>
  );
}
