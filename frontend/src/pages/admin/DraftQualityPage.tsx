// AI 초안 수정 분석 (/admin/drafts, 관리자): 상담원이 AI 초안을 그대로 보냈는지, 얼마나·어떻게 고쳤는지
// 그대로 보낸 비율(성공 지표 70%), 보낸 답변 중 AI가 쓴 글, 유형별·날짜별·상담원별, 다시 만들기 요청, 많이 고친 초안 비교
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";

import { Alert, Card, Spinner, cx, formatDate } from "../../components/ui";
import { errorMessage, statsApi } from "../../services/api";
import type { DraftLevel, DraftStats } from "../../services/types";

const pct = (v: number | null | undefined, digits = 0) => (v === null || v === undefined ? "-" : `${(v * 100).toFixed(digits)}%`);
const PERIODS = [14, 30, 90];
const LEVEL_STYLE: Record<DraftLevel, { bar: string; chip: string; note: string }> = {
  "그대로": { bar: "bg-emerald-500", chip: "bg-emerald-50 text-emerald-700 border-emerald-200", note: "글자 하나 안 바꾸고 보냄" },
  "조금 고침": { bar: "bg-amber-400", chip: "bg-amber-50 text-amber-800 border-amber-200", note: "인사말·한 문장 다듬기 (바뀐 정도 20% 미만)" },
  "많이 고침": { bar: "bg-rose-500", chip: "bg-rose-50 text-rose-700 border-rose-200", note: "내용을 바꾸거나 새로 씀 (20% 이상)" },
};

function waitText(min: number | null) {
  if (min === null) return "-";
  if (min < 60) return `${Math.round(min)}분`;
  return `${(min / 60).toFixed(1)}시간`;
}

function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "bad" }) {
  return (
    <div className={cx("rounded-2xl border px-4 py-3",
      tone === "good" ? "border-emerald-300 bg-emerald-50" : tone === "bad" ? "border-rose-300 bg-rose-50" : "border-slate-300 bg-white")}>
      <div className="text-sm text-slate-600">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-sm text-slate-600">{sub}</div>}
    </div>
  );
}

/** 0~1 비율 막대 (목표선 표시) */
function RateBar({ value, target }: { value: number | null; target?: number }) {
  return (
    <div className="relative h-2.5 w-full rounded-full bg-slate-100">
      {value !== null && (
        <div className={cx("h-2.5 rounded-full", target !== undefined && value < target ? "bg-amber-400" : "bg-emerald-500")}
          style={{ width: `${Math.max(2, value * 100)}%` }} />
      )}
      {target !== undefined && <div className="absolute -top-1 h-4.5 w-0.5 bg-slate-500" style={{ left: `${target * 100}%` }} title={`목표 ${pct(target)}`} />}
    </div>
  );
}

export default function DraftQualityPage() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<DraftStats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setError("");
    statsApi.drafts(days).then(setData).catch((err) => setError(errorMessage(err)));
  }, [days]);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <p className="p-6 text-center text-slate-500"><Spinner /></p>;
  const s = data.summary;
  const passed = s.unedited_rate !== null && s.unedited_rate >= s.target;
  const maxDay = Math.max(1, ...data.daily.map((d) => d.count));
  const weakest = data.by_category.filter((g) => g.count >= 2 && g.unedited_rate !== null)
    .sort((a, b) => (a.unedited_rate ?? 1) - (b.unedited_rate ?? 1))[0];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">AI 초안 수정 분석</h1>
          <p className="mt-1 text-[15px] text-slate-600">
            상담원이 승인해 보낸 AI 초안을 실제로 보낸 답변과 비교합니다. 고치지 않고 보낼수록 AI가 상담원 일을 덜어 준 것이고,
            많이 고친 유형은 FAQ·프롬프트를 손볼 곳입니다 · {data.range.from} ~ {data.range.to} (보낸 날짜, 한국 시간)
          </p>
        </div>
        <div className="flex rounded-xl border border-slate-300 bg-white p-1" role="group" aria-label="기간">
          {PERIODS.map((d) => (
            <button key={d} onClick={() => setDays(d)} aria-pressed={days === d}
              className={cx("rounded-lg px-3 py-1.5 text-sm", days === d ? "bg-primary font-semibold text-white" : "text-body hover:bg-surface-card")}>
              {d}일
            </button>
          ))}
        </div>
      </div>

      {s.count === 0 ? (
        <Alert kind="info">이 기간에 상담원이 승인해 보낸 AI 초안이 없습니다. 기간을 늘려 보세요.</Alert>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="고치지 않고 보낸 비율" value={pct(s.unedited_rate, 1)} tone={passed ? "good" : "bad"}
              sub={`${s.count}건 중 ${s.unedited}건 · 목표 ${pct(s.target)} 이상 ${passed ? "달성" : "미달"}`} />
            <Stat label="보낸 답변 중 AI가 쓴 글" value={pct(s.ai_share, 1)} sub="고친 답변까지 포함한 글자 비율" />
            <Stat label="평균 바뀐 정도" value={pct(s.avg_change, 1)} sub="0% = 그대로, 100% = 완전히 새로 씀" />
            <Stat label="초안 → 발송 (중앙값)" value={waitText(s.median_wait_min)}
              sub={<>지금 검토 기다리는 초안 <Link to="/admin/inquiries" className="font-semibold text-primary hover:underline">{s.waiting}건</Link></>} />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="얼마나 고쳤나">
              <div className="flex h-7 w-full overflow-hidden rounded-lg" role="img"
                aria-label={(Object.keys(LEVEL_STYLE) as DraftLevel[]).map((lv) => `${lv} ${s.levels[lv]}건`).join(", ")}>
                {(Object.keys(LEVEL_STYLE) as DraftLevel[]).map((lv) => s.levels[lv] > 0 && (
                  <div key={lv} className={cx(LEVEL_STYLE[lv].bar, "flex items-center justify-center text-sm font-semibold text-white")}
                    style={{ width: `${(s.levels[lv] / s.count) * 100}%` }}>{s.levels[lv]}</div>
                ))}
              </div>
              <ul className="mt-4 space-y-2">
                {(Object.keys(LEVEL_STYLE) as DraftLevel[]).map((lv) => (
                  <li key={lv} className="flex items-start gap-3 text-[15px]">
                    <span className={cx("mt-1.5 h-3 w-3 shrink-0 rounded-sm", LEVEL_STYLE[lv].bar)} aria-hidden />
                    <div>
                      <b className="text-ink">{lv}</b>
                      <span className="ml-2 tabular-nums text-slate-700">{s.levels[lv]}건 ({pct(s.levels[lv] / s.count)})</span>
                      <p className="text-sm text-slate-600">{LEVEL_STYLE[lv].note}</p>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="mt-4 border-t border-slate-200 pt-3 text-sm text-slate-700">
                <span className="font-semibold text-ink">고친 방식</span>
                <span className="ml-3">덧붙임 {s.kinds["덧붙임"]}건</span>
                <span className="ml-3">줄임 {s.kinds["줄임"]}건</span>
                <span className="ml-3">고쳐 씀 {s.kinds["고쳐 씀"]}건</span>
                <p className="mt-1 text-slate-600">덧붙임 = 지운 것 없이 더함 (일정·금액·사과 추가), 줄임 = 지우기만 함, 고쳐 씀 = 지우고 새로 씀</p>
              </div>
            </Card>

            <Card title="날짜별 보낸 초안">
              <div className="flex h-36 items-end gap-0.5" role="img" aria-label="날짜별 보낸 AI 초안과 그대로 보낸 수">
                {data.daily.map((d) => (
                  <div key={d.date} className="flex h-full flex-1 flex-col justify-end" title={`${d.date} · ${d.count}건 중 그대로 ${d.unedited}건`}>
                    {d.count > d.unedited && <div className="bg-amber-400" style={{ height: `${((d.count - d.unedited) / maxDay) * 100}%` }} />}
                    {d.unedited > 0 && <div className="rounded-b-sm bg-emerald-500" style={{ height: `${(d.unedited / maxDay) * 100}%` }} />}
                    {d.count === 0 && <div className="h-0.5 bg-slate-200" />}
                  </div>
                ))}
              </div>
              <div className="mt-1 flex justify-between text-xs text-slate-500">
                <span>{data.daily[0]?.date.slice(5)}</span><span>{data.daily[data.daily.length - 1]?.date.slice(5)}</span>
              </div>
              <p className="mt-2 flex gap-4 text-sm text-slate-600">
                <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-emerald-500" />그대로 보냄</span>
                <span><span className="mr-1 inline-block h-2.5 w-2.5 rounded-sm bg-amber-400" />고쳐서 보냄</span>
              </p>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <Card title="문의 유형별">
              {weakest && weakest.unedited_rate! < s.target && (
                <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <b>{weakest.category}</b> 초안을 가장 많이 고칩니다 (그대로 {pct(weakest.unedited_rate)}).
                  아래 비교를 보고 FAQ 답변이나 초안 프롬프트에 빠진 내용을 채우면 좋습니다.
                </p>
              )}
              <table className="w-full text-left text-[15px]">
                <thead className="text-sm text-slate-600">
                  <tr><th className="py-1.5 font-medium">유형</th><th className="py-1.5 font-medium">건수</th>
                    <th className="w-2/5 py-1.5 font-medium">그대로 보낸 비율</th><th className="py-1.5 text-right font-medium">평균 바뀐 정도</th></tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {data.by_category.map((g) => (
                    <tr key={g.category}>
                      <td className="py-2 font-medium text-ink">{g.category}</td>
                      <td className="py-2 tabular-nums">{g.count}</td>
                      <td className="py-2 pr-3">
                        <div className="flex items-center gap-2"><RateBar value={g.unedited_rate} target={s.target} />
                          <span className="w-12 shrink-0 text-right tabular-nums">{pct(g.unedited_rate)}</span></div>
                      </td>
                      <td className="py-2 text-right tabular-nums">{pct(g.avg_change, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-sm text-slate-600">막대의 세로선 = 목표 {pct(s.target)}</p>
            </Card>

            <div className="space-y-4">
              <Card title="상담원별">
                <ul className="divide-y divide-slate-200">
                  {data.by_staff.map((g) => (
                    <li key={g.id} className="flex items-center gap-3 py-2 text-[15px]">
                      <b className="w-24 shrink-0 truncate text-ink">{g.display_name}</b>
                      <span className="w-12 shrink-0 tabular-nums text-slate-700">{g.count}건</span>
                      <RateBar value={g.unedited_rate} target={s.target} />
                      <span className="w-12 shrink-0 text-right tabular-nums">{pct(g.unedited_rate)}</span>
                    </li>
                  ))}
                </ul>
              </Card>
              <Card title="초안 다시 만들기">
                <p className="text-[15px] text-slate-700">
                  [AI 초안 만들기]를 다시 누른 횟수 <b className="tabular-nums text-ink">{data.regenerate.count}번</b>
                  {" "}· 요청을 적은 것 <b className="tabular-nums text-ink">{data.regenerate.with_instruction}번</b>
                </p>
                {data.regenerate.top_instructions.length > 0 ? (
                  <ul className="mt-2 flex flex-wrap gap-2">
                    {data.regenerate.top_instructions.map((t) => (
                      <li key={t.text} className="rounded-full border border-indigo-200 bg-indigo-50 px-3 py-1 text-sm text-indigo-800">
                        {t.text} <b className="tabular-nums">{t.count}</b>
                      </li>
                    ))}
                  </ul>
                ) : <p className="mt-2 text-sm text-slate-600">아직 요청을 적어 다시 만든 초안이 없습니다.</p>}
                <p className="mt-2 text-sm text-slate-600">자주 나오는 요청은 처음 초안부터 반영되도록 프롬프트에 넣을 후보입니다.</p>
              </Card>
            </div>
          </div>

          <Card title="많이 고친 초안 (바뀐 정도 순)">
            {data.examples.length === 0 && <p className="text-sm text-slate-600">고쳐서 보낸 초안이 없습니다. 모두 그대로 보냈습니다.</p>}
            <ul className="space-y-4">
              {data.examples.map((e) => (
                <li key={e.inquiry_id} className="rounded-xl border border-slate-300 p-4">
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <Link to={`/admin/inquiries/${e.inquiry_id}`}
                      className="rounded-md border border-slate-300 px-2 py-0.5 font-mono font-semibold text-primary hover:bg-primary-soft">
                      {e.inquiry_number}
                    </Link>
                    <b className="text-[15px] text-ink">{e.title}</b>
                    <span className="text-slate-600">{e.category} · {e.staff} · {formatDate(e.sent_at)}</span>
                    <span className={cx("ml-auto rounded-full border px-2.5 py-0.5 font-semibold", LEVEL_STYLE[e.level].chip)}>
                      {e.level} {pct(e.change)}{e.kind && ` · ${e.kind}`}
                    </span>
                  </div>
                  <p className="mt-3 whitespace-pre-wrap text-[15px] leading-7 text-slate-800">
                    {e.segments.map((g, k) => g.op === "same" ? <span key={k}>{g.text}</span>
                      : g.op === "del" ? <del key={k} className="bg-rose-100 text-rose-800 decoration-rose-500" title="AI 초안에서 지운 부분">{g.text}</del>
                        : <ins key={k} className="bg-emerald-100 text-emerald-900 no-underline" title="상담원이 더한 부분">{g.text}</ins>)}
                  </p>
                  <p className="mt-2 text-sm text-slate-600">
                    <del className="bg-rose-100 px-1 text-rose-800">빨간 줄</del> AI 초안에서 지움 {e.removed}자 ·
                    {" "}<ins className="bg-emerald-100 px-1 text-emerald-900 no-underline">초록</ins> 상담원이 더함 {e.added}자
                  </p>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
