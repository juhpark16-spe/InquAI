// 재학습 현황 (/admin/retraining, 관리자): 상담원이 고친 분류가 쌓여 다음 모델이 되는 과정을 보여 줌
// 재학습 권장 표시, 지금 쓰는 모델(읽기 쉬운 이름), 쌓인 수정·새 수정(다음 재학습 대상), 모델이 자주 틀리는 패턴,
// 최근 수정, 모델 버전별 점수. 재학습 명령어는 개발자용이라 접어 둠 (docs/retraining.md)
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";

import { Alert, Card, Spinner, cx, formatDate, monthDay } from "../../components/ui";
import { errorMessage, retrainingApi } from "../../services/api";
import type { ModelVersion, RetrainingStatus } from "../../services/types";

const pct = (v: number | undefined) => (v === undefined ? "-" : `${(v * 100).toFixed(1)}%`);

function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: boolean }) {
  return (
    <div className={cx("rounded-2xl border px-4 py-3", accent ? "border-primary/30 bg-primary-soft" : "border-hairline bg-white")}>
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

const STEPS: [string, string][] = [
  ["수정 데이터 내보내기 (data/corrections/, Git 제외)", "python -m backend.training.export_corrections"],
  ["학습 데이터 + 수정 데이터로 다시 학습 (GPU 약 15분, seed 3개 권장)",
    "python backend/training/train.py --data data/raw/inquiries_with_qa_ev.csv --label-column category --seed 42 \\\n  --output-dir models/category_new_s42 --report-name cat_new_s42 \\\n  --extra-train data/corrections/category_corrections.csv data/supplement/generated_weak.csv"],
  ["직접 쓴 평가용·외부 테스트로 비교", "python backend/training/evaluate.py --label-column category --model-dir models/category_new_s42 \\\n  --test-file data/test/written_eval.csv --report-name cat_new_s42_written_eval"],
  ["외부 테스트가 떨어지지 않으면 교체: models/category_classifier 에 복사, config.py 버전 이름·evaluation/model_history.json·docs/model_card.md 수정 후 서버 다시 켜기", ""],
];

/** 모델 버전 읽기 쉬운 이름: 학습한 순서대로 1차·2차… (코드명은 작게). 사용 중 / 이전 모델 / 시험만(채택 안 함) */
function versionNames(history: ModelVersion[]) {
  const sorted = [...history].sort((a, b) => (a.trained_at ?? "").localeCompare(b.trained_at ?? ""));
  const current = sorted.find((v) => v.current);
  return new Map(sorted.map((v, i) => {
    const tried = !v.current && (v.version.includes("(안)") || (!!current && (v.trained_at ?? "") > (current.trained_at ?? "")));
    const status = v.current ? "사용 중" : tried ? "시험만 (채택 안 함)" : "이전 모델";
    return [v.version, { name: `유형 분류 모델 ${i + 1}차`, status }];
  }));
}

const shortDate = (iso?: string) => monthDay(iso);

export default function RetrainingPage() {
  const [data, setData] = useState<RetrainingStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    retrainingApi.status().then(setData).catch((err) => setError(errorMessage(err)));
  }, []);

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <p className="p-6 text-center text-slate-500"><Spinner /></p>;
  const { model, corrections, patterns, recent, history } = data;
  const top = patterns.find((p) => p.field === "유형");
  const names = versionNames(history);
  const currentName = names.get(history.find((v) => v.current)?.version ?? "")?.name ?? "유형 분류 모델";

  return (
    <div className="space-y-5">
      <div>
        <h1 className="page-title">재학습 현황</h1>
        <p className="text-sm text-slate-500">
          상담원이 문의 상세에서 [분류 고치기]로 바로잡은 분류는 다음 모델의 학습 데이터가 됩니다.
          자주 고치는 패턴이 곧 모델의 약점입니다.
        </p>
      </div>

      {/* 재학습 권장: 기준을 넘으면 이유와 함께 (관리자가 숫자를 보고 따로 판단하지 않아도 되게) */}
      {data.recommend && (data.recommend.needed ? (
        <div className="rounded-2xl border border-primary/30 bg-primary-soft px-5 py-4">
          <p className="font-semibold text-primary">재학습을 권장해요</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-body">{data.recommend.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
          <p className="mt-1.5 text-xs text-muted">재학습은 개발자가 진행해요 (아래 '개발자용 · 재학습 방법'). 새 모델은 외부 테스트 점수가 떨어지지 않을 때만 바꿔요.</p>
        </div>
      ) : (
        <div className="rounded-2xl border border-hairline bg-white px-5 py-3 text-sm text-body">
          <b className="text-emerald-700">아직 재학습할 때가 아니에요.</b>{" "}
          새 수정이 {data.recommend.pending_threshold}건 이상 쌓이거나, 같은 패턴의 새 수정이 {data.recommend.pattern_threshold}건 이상 반복되면 알려 드려요.
        </div>
      ))}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="지금 쓰는 모델" value={currentName}
          sub={<>{model.trained_at ? `${shortDate(model.trained_at)} 학습 · 상담원 수정 ${model.corrections_used ?? 0}건 반영` : ""}
            <span className="ml-1 font-mono text-xs text-slate-400">{model.version}</span></>} />
        <Stat label="쌓인 분류 수정" value={`${corrections.total}건`}
          sub={Object.entries(corrections.by_field).map(([k, v]) => `${k} ${v}`).join(" · ")} />
        <Stat label="새 수정 (다음 재학습 대상)" value={`${corrections.pending}건`} accent={corrections.pending > 0}
          sub="지금 모델 학습 뒤에 쌓인 수정" />
        <Stat label="가장 많이 고친 패턴" value={top ? `${top.before} → ${top.after}` : "-"} sub={top ? `${top.count}건` : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="모델이 자주 틀리는 패턴">
          {patterns.length === 0 && <p className="text-sm text-slate-500">아직 분류 수정이 없습니다.</p>}
          <ul className="space-y-3">
            {patterns.map((p) => (
              <li key={`${p.field}-${p.before}-${p.after}`} className="rounded-xl border border-hairline p-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="text-xs text-muted">{p.field}</span>
                  <span className="rounded-full bg-rose-50 px-2 py-0.5 text-rose-700 line-through decoration-rose-300">{p.before}</span>
                  <span className="text-slate-400">→</span>
                  <span className="rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700">{p.after}</span>
                  <span className="ml-auto text-xs tabular-nums text-slate-500">{p.count}건{p.pending > 0 && <b className="ml-1 text-primary">새 {p.pending}</b>}</span>
                </div>
                <ul className="mt-2 space-y-0.5 text-xs text-body">
                  {p.examples.map((e, i) => (
                    <li key={i} className="truncate">
                      <Link to={`/admin/inquiries/${e.inquiry_id}`} className="text-primary hover:underline">문의</Link> {e.text}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        </Card>

        <Card title="최근 분류 수정">
          {recent.length === 0 && <p className="text-sm text-slate-500">아직 분류 수정이 없습니다.</p>}
          <ul className="divide-y divide-hairline">
            {recent.map((c) => (
              <li key={c.id} className="py-2 text-sm">
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <Link to={`/admin/inquiries/${c.inquiry_id}`} className="font-mono text-primary hover:underline">{c.inquiry_number}</Link>
                  <span>{c.field} {c.before} → <b className="text-ink">{c.after}</b></span>
                  <span>{formatDate(c.at)}</span>
                  {c.pending && <span className="rounded-full bg-primary-soft px-2 text-primary">새 수정</span>}
                </div>
                <p className="mt-0.5 truncate text-body" title={c.text}>{c.text}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="모델 버전 기록">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[50rem] text-left text-sm">
            <thead className="text-sm text-muted">
              <tr>{["모델", "학습일", "학습 데이터", "외부 테스트", "직접 쓴 평가용", "새 평가용 (2차)", "실전 100", "메모"].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {history.map((v) => (
                <tr key={v.version} className={cx("align-top", v.current && "bg-primary-soft/50")}>
                  <td className="whitespace-nowrap px-2 py-2">
                    <span className="font-medium text-ink">{names.get(v.version)?.name}</span>
                    <span className={cx("ml-1 rounded-full px-2 py-0.5 text-xs",
                      v.current ? "bg-primary text-white" : names.get(v.version)?.status === "이전 모델" ? "bg-slate-100 text-slate-600" : "bg-amber-50 text-amber-700")}>
                      {names.get(v.version)?.status}
                    </span>
                    <span className="block font-mono text-xs text-slate-400">{v.version} · {v.base_model ?? "-"}</span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-slate-600">{shortDate(v.trained_at) || "-"}</td>
                  <td className="px-2 py-2 text-sm text-body">{v.data ?? "-"}</td>
                  <td className="px-2 py-2 tabular-nums">{pct(v.scores.external)}</td>
                  <td className="px-2 py-2 tabular-nums">{pct(v.scores.written_eval)}</td>
                  <td className="px-2 py-2 tabular-nums">{pct(v.scores.written_eval2)}</td>
                  <td className="px-2 py-2 tabular-nums">{pct(v.scores.real)}</td>
                  <td className="px-2 py-2 text-sm text-slate-500">{v.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-slate-500">외부 테스트(AI Hub 753건)가 주 기준입니다. 재학습한 모델은 외부 테스트가 떨어지지 않을 때만 교체합니다.</p>
      </Card>

      {/* 재학습 명령어는 개발자가 터미널에서 할 일 → 접어 둠 (자세한 내용은 docs/retraining.md) */}
      <details className="group rounded-2xl border border-hairline bg-white">
        <summary className="cursor-pointer list-none px-6 py-4 text-lg font-semibold text-ink hover:text-primary">
          개발자용 · 재학습 방법 <span className="text-sm font-normal text-muted"><span className="group-open:hidden">펼치기 ▾</span><span className="hidden group-open:inline">접기 ▴</span></span>
        </summary>
        <div className="border-t border-hairline px-6 pb-5 pt-3">
        <p className="mb-3 text-sm text-slate-500">GPU가 필요하고 시간이 걸려 화면 버튼 대신 서버에서 명령으로 실행합니다. 자세한 내용은 docs/retraining.md</p>
        <ol className="space-y-3 text-sm">
          {STEPS.map(([title, cmd], i) => (
            <li key={i}>
              <p className="font-medium text-ink">{i + 1}. {title}</p>
              {cmd && <pre className="mt-1 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">{cmd}</pre>}
            </li>
          ))}
        </ol>
        </div>
      </details>
    </div>
  );
}
