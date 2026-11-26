// 관리자 대시보드 (/admin): 지금 처리할 일 → 기간 지표(지난 기간 대비) → 날짜별 유형 → 처리 현황·만족도·담당자·상품
// (최근 활동·LLM 호출·토큰은 뺌: 문의 상세의 처리 이력과 AI 실행 로그에서 봄)
// → 처리·미처리, 처리 방식·긴급도 → AI 현황, 담당자별 미처리 → 문의가 많은 상품 (상세페이지 개선 신호)
// 색: 카드는 흰 바탕, 위험한 값(기한 초과·긴급)만 빨강. 유형 8개는 고정 순서의 범주 색(유형마다 항상 같은 색)
// 파일: 이 파일은 데이터 불러오기·배치만. 카드·지표·그래프 부품과 색은 dashboard/widgets.tsx
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useAuth } from "../../auth/AuthProvider";
import Icon from "../../components/Icon";
import { Alert, Spinner, cx, initialOf } from "../../components/ui";
import { errorMessage, statsApi, type Priorities, type ProductStats, type StatsSummary } from "../../services/api";
import { CATEGORIES } from "../../services/types";
import { CATEGORY_COLOR, CRITICAL, ChartTooltip, Delta, DueSoon, HATCH, INK, Kpi, LegendRow, NextUp, Panel, Products, Rechecks, SERIES, ShareBars, WorkCard, pct, shortDate } from "./dashboard/widgets";

export default function DashboardPage() {
  const { user } = useAuth();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<StatsSummary | null>(null);
  const [error, setError] = useState("");
  const [showTable, setShowTable] = useState(false);
  const [products, setProducts] = useState<ProductStats | null>(null);
  const [prio, setPrio] = useState<Priorities | null | undefined>(undefined);

  useEffect(() => {
    setError("");
    statsApi.summary(days).then(setData).catch((err) => setError(errorMessage(err)));
    statsApi.products(Math.max(days, 30)).then(setProducts).catch(() => setProducts(null));  // 상품별은 최소 30일 (건수가 적어서)
  }, [days]);

  useEffect(() => {
    statsApi.priorities(5).then(setPrio).catch(() => setPrio(null));
  }, []);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <p className="p-6 text-center text-muted"><Spinner /></p>;

  const daily = data.daily.map((d) => ({ date: shortDate(d.date), ...d.by_category, 처리됨: d.done, 미처리: d.open }));
  const analyzed = Object.values(data.by_category).reduce((a, b) => a + b, 0);
  const axis = { stroke: INK.axis, tick: { fill: INK.muted, fontSize: 13 }, tickLine: false };
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
          <h1 className="page-title">{hello}, {user?.display_name}님</h1>
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
        <h2 className="mb-3 text-lg font-semibold text-ink">지금 처리할 일 <span className="font-normal text-muted">· 기간과 관계없이 현재</span></h2>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <WorkCard label="답변 기한 초과" value={data.now.overdue_open} sub="주말 제외 · 긴급 4시간 · 그 외 24시간"
            to="/admin/inquiries?overdue=true" critical highlight />
          <WorkCard label="긴급 미처리" value={data.now.urgent_open} sub="긴급도 높음"
            to="/admin/inquiries?open=true&urgency=높음" critical />
          <WorkCard label="미처리 전체" value={data.now.open} sub="접수·검토 대기·담당자 처리" to="/admin/inquiries?open=true" />
          <WorkCard label="검토 대기" value={data.now.review_waiting} sub="AI 초안 확인 필요" to="/admin/inquiries?status=검토 대기" />
          <WorkCard label="미배정" value={data.now.unassigned_open} sub="담당자 없음" to="/admin/inquiries?open=true&assigned_to=none" />
          <WorkCard label="승인 대기 요청" value={data.now.pending_tickets ?? 0} sub="취소·교환·반품" to="/admin/tickets" />
        </div>
        <div className="mt-3 grid gap-3 lg:grid-cols-[2fr_3fr]">
          <NextUp item={prio?.next} open={prio?.open ?? data.now.open} failed={prio === null} />
          <DueSoon items={prio?.due_soon} overdue={data.now.overdue_open} failed={prio === null} />
        </div>
        {prio && <Rechecks items={prio.rechecks ?? []} total={prio.recheck_total ?? 0} />}
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
          delta={null} compare={<>AI 초안을 고치지 않고 보낸 비율 · 목표 70% 이상 · <Link to="/admin/drafts" className="font-semibold text-primary hover:underline">자세히</Link></>} />
        <Kpi label="AI 평균 처리 시간" value={sec(data.ai.avg_latency_ms)}
          delta={<Delta value={change(data.ai.avg_latency_ms, prev.avg_latency_ms)} unit="%" goodWhenUp={false} />}
          compare={`지난 ${days}일 ${sec(prev.avg_latency_ms)} · 목표 10초 이내`} />
      </section>

      <div>
        <Panel icon="dashboard" title="날짜별 문의 유형" sub="유형마다 같은 색으로 쌓아 보여 줍니다"
          action={
            <button className="rounded-lg border border-hairline px-3 py-1.5 text-xs font-medium text-ink hover:bg-surface-card"
              onClick={() => setShowTable(!showTable)}>
              {showTable ? "그래프로 보기" : "표로 보기"}
            </button>}>
          {showTable ? (
            <div className="overflow-x-auto">
              <table className="w-full text-right text-sm tabular-nums">
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
                <defs>
                  <pattern id="hatch-open" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                    <rect width="6" height="6" fill="#fff" />
                    <line x1="0" y1="0" x2="0" y2="6" stroke={SERIES[1]} strokeWidth="3" />
                  </pattern>
                </defs>
                <Bar dataKey="미처리" stackId="s" fill={HATCH} stroke={SERIES[1]} strokeWidth={1} maxBarSize={40} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <LegendRow items={[["처리됨", SERIES[0]], ["미처리", HATCH]]} />
        </Panel>

        <Panel icon="zap" title="처리 방식 · 긴급도" sub={`분석된 ${analyzed}건`}>
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
            <dt className="text-muted" title="AI가 문의 유형을 80% 미만으로 확신해 자동 답변하지 않고 상담원에게 넘김">유형 판단 불확실 (80% 미만) → 상담원</dt><dd className="text-right tabular-nums text-ink">{data.ai.low_confidence}건</dd>
            <dt className="text-muted">AI 오류·시간 초과</dt>
            <dd className={cx("text-right tabular-nums", data.ai.errors ? "font-semibold text-rose-700" : "text-ink")}>{data.ai.errors}건</dd>
            <dt className="text-muted" title="상담원이 고친 유형·감정. 재학습 데이터로 모읍니다">분류 수정 (재학습 데이터)</dt>
            <dd className="text-right tabular-nums text-ink">
              유형 {data.ai.corrections.category}건 · 감정 {data.ai.corrections.sentiment}건
            </dd>
            <dt className="text-muted">답변 초안 작성 실패</dt>
            <dd className={cx("text-right tabular-nums", data.ai.draft_failures ? "font-semibold text-amber-700" : "text-ink")}>{data.ai.draft_failures}건</dd>
          </dl>
        </Panel>

        <Panel icon="users" title="담당자별 미처리" sub="지금 맡고 있는 문의"
          action={<Link to="/admin/inquiries?open=true" className="flex items-center gap-1 text-xs font-medium text-ink hover:underline">전체 보기 <Icon name="arrow" className="h-3.5 w-3.5" /></Link>}>
          <ul className="divide-y divide-hairline">
            {data.staff.map((s) => (
              <li key={s.id} className="first:pt-0">
                {/* 누르면 그 사람이 맡은 미처리 문의 목록 */}
                <Link to={`/admin/inquiries?open=true&assigned_to=${s.id}`} className="-mx-2 flex items-center gap-3 rounded-xl px-2 py-2.5 hover:bg-surface-soft">
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
                </Link>
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
