// 관리자 대시보드 (/admin): 지금 처리할 일 → 기간 지표(지난 기간 대비) → 날짜별 유형 → 처리 현황·만족도·담당자·상품
// (최근 활동·LLM 호출·토큰은 뺌: 문의 상세의 처리 이력과 AI 실행 로그에서 봄)
// → 처리·미처리, 처리 방식·긴급도 → AI 현황, 담당자별 미처리 → 문의가 많은 상품 (상세페이지 개선 신호)
// 색: 카드는 흰 바탕, 위험한 값(기한 초과·긴급)만 빨강. 유형 8개는 고정 순서의 범주 색(유형마다 항상 같은 색)
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useAuth } from "../../auth/AuthProvider";
import Icon, { type IconName } from "../../components/Icon";
import { Alert, Badge, Spinner, cx, formatDate, initialOf } from "../../components/ui";
import { errorMessage, statsApi, type Priorities, type PriorityItem, type ProductStats, type StatsSummary } from "../../services/api";
import { CATEGORIES } from "../../services/types";

// 범주 색 8개 (색약 구분 검증된 순서, 유형 순서와 1:1로 고정)
const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
// 유형 색: 빨강·초록은 '나쁨·좋음' 표시에만 쓰므로 유형에는 쓰지 않음 (배송 파랑, 주문 취소 주황, 교환 하늘,
// 반품·환불 노랑, 결제 분홍, 상품 보라, 쿠폰·적립금·회원 갈색, 기타 회색)
const CATEGORY_PALETTE = ["#2a78d6", "#eb6834", "#22a6c8", "#e5a000", "#d6589e", "#6a4fd6", "#9b6a3c", "#8b95a3"];
const CATEGORY_COLOR = Object.fromEntries(CATEGORIES.map((c, i) => [c, CATEGORY_PALETTE[i]]));
const INK = { muted: "#6a6a6a", grid: "#ebe6d6", axis: "#d9d2c0" };
const CRITICAL = "#d03b3b";
// 미처리는 새 색 대신 빗금으로 (처리됨과 색만으로 구분하지 않아도 됨, 색 구분이 어려운 사람도 알아봄)
const HATCH = "url(#hatch-open)";
const HATCH_CSS = `repeating-linear-gradient(45deg, ${SERIES[1]} 0 2px, #fff 2px 5px)`;
const swatch = (color: string) => (color === HATCH ? HATCH_CSS : color);

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${Math.round(v * 100)}%`);
const shortDate = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;

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
            <h2 className="text-lg font-semibold text-ink">{title}</h2>
            {sub && <p className="text-xs text-muted">{sub}</p>}
          </div>
        </div>
        {action}
      </header>
      <div className="p-5">{children}</div>
    </section>
  );
}

/** 지금 처리할 일 카드: 누르면 해당 목록으로 (오른쪽 위 ↗).
 *  highlight: 가장 중요한 카드(답변 기한 초과)는 값이 있으면 진한 빨강으로 채워 먼저 눈에 들어오게 */
function WorkCard({ label, value, sub, to, critical, highlight }: {
  label: string; value: number; sub: string; to: string; critical?: boolean; highlight?: boolean;
}) {
  const alarm = critical && value > 0;
  const filled = highlight && value > 0;
  return (
    <Link to={to} className={cx("group block rounded-2xl border p-4 transition hover:-translate-y-0.5",
      filled ? "border-rose-700 bg-rose-600 text-white shadow-md shadow-rose-600/25"
        : alarm ? "border-rose-200 bg-white" : "border-hairline bg-white")}>
      <div className="flex items-start justify-between gap-2">
        <p className={cx("text-base", filled ? "font-semibold text-white" : alarm ? "font-semibold text-rose-700" : "text-body")}>{label}</p>
        <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-full border transition",
          filled ? "border-white/60 bg-white text-rose-600" : "border-hairline text-ink group-hover:border-primary group-hover:text-primary")}
          aria-hidden>
          <Icon name="arrow" className="h-4 w-4 -rotate-45" />
        </span>
      </div>
      <p className={cx("display mt-1 text-4xl tabular-nums", filled ? "!text-white" : alarm && "!text-rose-700")}>{value}</p>
      <p className={cx("mt-1 text-xs", filled ? "text-white/85" : "text-muted")}>{sub}</p>
    </Link>
  );
}

/** 답변 기한까지 남은 시간 ("1시간 20분 남음" / "3시간 지남") */
function dueLabel(due: string) {
  const mins = Math.round((new Date(due).getTime() - Date.now()) / 60_000);
  const abs = Math.abs(mins);
  const h = Math.floor(abs / 60);
  const text = abs < 60 ? `${abs}분` : h < 24 ? `${h}시간${abs % 60 ? ` ${abs % 60}분` : ""}` : `${Math.floor(h / 24)}일${h % 24 ? ` ${h % 24}시간` : ""}`;
  return { text: mins < 0 ? `${text} 지남` : `${text} 남음`, mins };
}

function DuePill({ due, overdue }: { due: string; overdue: boolean }) {
  const { text, mins } = dueLabel(due);
  return (
    <span className={cx("shrink-0 rounded-full px-2.5 py-0.5 text-sm font-semibold tabular-nums",
      overdue ? "bg-rose-600 text-white" : mins <= 120 ? "bg-amber-100 text-amber-800" : "bg-surface-card text-body")}>
      {overdue ? "⏰ " : ""}{text}
    </span>
  );
}

/** 지금 가장 급한 문의: 처리 대기열의 첫 문의 (긴급도 → 오래된 순) + [바로 처리] */
function NextUp({ item, open, failed }: { item: PriorityItem | null | undefined; open: number; failed: boolean }) {
  return (
    <section className="flex flex-col rounded-2xl border border-hairline bg-white p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-ink">지금 가장 급한 문의</h2>
        {item && <DuePill due={item.due_at} overdue={item.overdue} />}
      </div>
      {failed ? <p className="flex-1 py-8 text-center text-base text-muted">불러오지 못했어요. 새로고침해 주세요.</p>
        : item === undefined ? <p className="py-8 text-center text-muted"><Spinner /></p> : !item ? (
        <p className="flex-1 py-8 text-center text-base text-muted">미처리 문의가 없어요. 모두 처리했습니다 🎉</p>
      ) : (
        <>
          <div className="mt-3 flex-1">
            <p className="text-xl font-semibold leading-snug text-ink">{item.title}</p>
            <p className="mt-1 line-clamp-2 text-sm text-muted">{item.preview}</p>
            <p className="mt-3 flex flex-wrap items-center gap-1.5 text-sm text-body">
              {item.urgency && <Badge value={item.urgency} />}
              <span>{item.category ?? "분석 전"}</span>
              <span className="text-muted">·</span>
              <span>{item.customer_name}</span>
              <span className="text-muted">·</span>
              <span>{item.assigned_to ?? "미배정"}</span>
            </p>
          </div>
          <Link to={`/admin/inquiries/${item.id}`}
            className="mt-4 flex min-h-12 items-center justify-center gap-2 rounded-xl bg-primary px-5 text-base font-semibold text-white shadow-sm shadow-primary/25 hover:bg-primary-hover">
            바로 처리 <Icon name="arrow" className="h-4 w-4" />
          </Link>
          <p className="mt-2 text-center text-xs text-muted">처리하면 상세 화면에서 다음 미처리 문의로 이어집니다 · 미처리 {open}건</p>
        </>
      )}
    </section>
  );
}

/** 기한 임박 문의: 아직 기한이 남은 미처리 문의를 기한이 가까운 순으로 */
function DueSoon({ items, overdue, failed }: { items: PriorityItem[] | undefined; overdue: number; failed: boolean }) {
  return (
    <section className="rounded-2xl border border-hairline bg-white p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-ink">기한 임박 문의</h2>
        {overdue > 0 && (
          <Link to="/admin/inquiries?overdue=true" className="text-sm font-semibold text-rose-700 hover:underline">기한 초과 {overdue}건 보기 →</Link>
        )}
      </div>
      {failed ? <p className="py-8 text-center text-base text-muted">불러오지 못했어요. 새로고침해 주세요.</p>
        : items === undefined ? <p className="py-8 text-center text-muted"><Spinner /></p> : items.length === 0 ? (
        <p className="py-8 text-center text-base text-muted">기한이 남은 미처리 문의가 없어요.</p>
      ) : (
        <ul className="mt-2 divide-y divide-hairline">
          {items.map((i) => (
            <li key={i.id}>
              <Link to={`/admin/inquiries/${i.id}`} className="flex items-center gap-3 rounded-lg py-2.5 hover:bg-surface-soft">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-base font-medium text-ink">{i.title}</span>
                  <span className="block truncate text-sm text-muted">
                    {i.category ?? "분석 전"} · {i.customer_name} · {i.assigned_to ?? "미배정"}
                  </span>
                </span>
                <DuePill due={i.due_at} overdue={i.overdue} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** 확인 후 다시 안내할 문의: "확인 후 안내드리겠습니다"를 먼저 보낸 문의 (다시 안내 기한 가까운 순). 있을 때만 보임 */
function Rechecks({ items, total }: { items: Priorities["rechecks"]; total: number }) {
  if (!total) return null;
  return (
    <section className="mt-3 rounded-2xl border border-hairline bg-white p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-ink">🔁 다시 안내할 문의 <span className="font-normal text-muted">{total}건</span></h2>
        <Link to="/admin/inquiries?recheck=true" className="text-sm font-semibold text-primary hover:underline">전체 보기 →</Link>
      </div>
      <ul className="mt-2 divide-y divide-hairline">
        {items.map((i) => (
          <li key={i.id}>
            <Link to={`/admin/inquiries/${i.id}`} className="flex items-center gap-3 rounded-lg py-2.5 hover:bg-surface-soft">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-base font-medium text-ink">{i.title}</span>
                <span className="block truncate text-sm text-muted">확인할 내용: {i.recheck_note} · {i.assigned_to ?? "미배정"}</span>
              </span>
              <span className={cx("shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold",
                i.recheck_overdue ? "bg-rose-50 text-rose-700" : "bg-blue-50 text-blue-700")}>
                {i.recheck_overdue ? "기한 지남" : formatDate(i.recheck_due_at)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
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
          <span className="inline-block h-3 w-3 rounded-sm" style={{ background: swatch(color) }} />{name}
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
          <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: swatch(p.color) }} />{p.name}
          <span className="ml-auto pl-3 tabular-nums">{p.value}</span>
        </p>
      ))}
    </div>
  );
}

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
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          <WorkCard label="답변 기한 초과" value={data.now.overdue_open} sub="주말 제외 · 긴급 4시간 · 그 외 24시간"
            to="/admin/inquiries?overdue=true" critical highlight />
          <WorkCard label="긴급 미처리" value={data.now.urgent_open} sub="긴급도 높음"
            to="/admin/inquiries?open=true&urgency=높음" critical />
          <WorkCard label="미처리 전체" value={data.now.open} sub="접수·검토 대기·담당자 처리" to="/admin/inquiries?open=true" />
          <WorkCard label="검토 대기" value={data.now.review_waiting} sub="AI 초안 확인 필요" to="/admin/inquiries?status=검토 대기" />
          <WorkCard label="미배정" value={data.now.unassigned_open} sub="담당자 없음" to="/admin/inquiries?open=true&assigned_to=none" />
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
