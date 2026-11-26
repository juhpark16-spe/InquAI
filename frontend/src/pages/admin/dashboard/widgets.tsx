// 대시보드 부품: 색, 카드(Panel·WorkCard), 지금 처리할 일·기한 임박·다시 안내 목록, 지표(Kpi·Delta·Spark), 비율 막대·상품·범례·그래프 말풍선
import type { ReactNode } from "react";
import { Link } from "react-router";
import Icon, { type IconName } from "../../../components/Icon";
import { Badge, Spinner, cx, formatDate } from "../../../components/ui";
import type { Priorities, PriorityItem, ProductStats } from "../../../services/api";
import { CATEGORIES } from "../../../services/types";

// 범주 색 8개 (색약 구분 검증된 순서, 유형 순서와 1:1로 고정)
export const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
// 유형 색: 빨강·초록은 '나쁨·좋음' 표시에만 쓰므로 유형에는 쓰지 않음 (배송 파랑, 주문 취소 주황, 교환 하늘,
// 반품·환불 노랑, 결제 분홍, 상품 보라, 쿠폰·적립금·회원 갈색, 기타 회색)
export const CATEGORY_PALETTE = ["#2a78d6", "#eb6834", "#22a6c8", "#e5a000", "#d6589e", "#6a4fd6", "#9b6a3c", "#8b95a3"];
export const CATEGORY_COLOR = Object.fromEntries(CATEGORIES.map((c, i) => [c, CATEGORY_PALETTE[i]]));
export const INK = { muted: "#6a6a6a", grid: "#ebe6d6", axis: "#d9d2c0" };
export const CRITICAL = "#d03b3b";
// 미처리는 새 색 대신 빗금으로 (처리됨과 색만으로 구분하지 않아도 됨, 색 구분이 어려운 사람도 알아봄)
export const HATCH = "url(#hatch-open)";
export const HATCH_CSS = `repeating-linear-gradient(45deg, ${SERIES[1]} 0 2px, #fff 2px 5px)`;
export const swatch = (color: string) => (color === HATCH ? HATCH_CSS : color);

export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${Math.round(v * 100)}%`);
export const shortDate = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8, 10))}`;

/** 흰 카드 + 머리글(아이콘 상자, 제목, 설명, 오른쪽 버튼) */
export function Panel({ icon, title, sub, action, children, className }: {
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
export function WorkCard({ label, value, sub, to, critical, highlight }: {
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
export function dueLabel(due: string) {
  const mins = Math.round((new Date(due).getTime() - Date.now()) / 60_000);
  const abs = Math.abs(mins);
  const h = Math.floor(abs / 60);
  const text = abs < 60 ? `${abs}분` : h < 24 ? `${h}시간${abs % 60 ? ` ${abs % 60}분` : ""}` : `${Math.floor(h / 24)}일${h % 24 ? ` ${h % 24}시간` : ""}`;
  return { text: mins < 0 ? `${text} 지남` : `${text} 남음`, mins };
}

export function DuePill({ due, overdue }: { due: string; overdue: boolean }) {
  const { text, mins } = dueLabel(due);
  return (
    <span className={cx("shrink-0 rounded-full px-2.5 py-0.5 text-sm font-semibold tabular-nums",
      overdue ? "bg-rose-600 text-white" : mins <= 120 ? "bg-amber-100 text-amber-800" : "bg-surface-card text-body")}>
      {overdue ? "⏰ " : ""}{text}
    </span>
  );
}

/** 지금 가장 급한 문의: 처리 대기열의 첫 문의 (긴급도 → 오래된 순) + [바로 처리] */
export function NextUp({ item, open, failed }: { item: PriorityItem | null | undefined; open: number; failed: boolean }) {
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
export function DueSoon({ items, overdue, failed }: { items: PriorityItem[] | undefined; overdue: number; failed: boolean }) {
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
export function Rechecks({ items, total }: { items: Priorities["rechecks"]; total: number }) {
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
export function Delta({ value, unit, goodWhenUp = true }: { value: number | null; unit: "%" | "%p"; goodWhenUp?: boolean }) {
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
export function Spark({ values }: { values: number[] }) {
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

export function Kpi({ label, value, delta, compare, spark }: { label: string; value: ReactNode; delta: ReactNode; compare: ReactNode; spark?: number[] }) {
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
export function ShareBars({ items, color, total }: { items: [string, number][]; color: (k: string) => string; total: number }) {
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
export function Products({ data }: { data: ProductStats | null }) {
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
export function LegendRow({ items }: { items: [string, string][] }) {
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

export function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
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
