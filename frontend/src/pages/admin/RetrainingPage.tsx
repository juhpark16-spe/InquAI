// 재학습 현황 (/admin/retraining, 관리자): 상담원이 고친 분류가 쌓여 다음 모델이 되는 과정을 보여 줌
// 쌓인 수정·새 수정(다음 재학습 대상), 모델이 자주 틀리는 패턴, 최근 수정, 모델 버전별 점수, 재학습 방법
import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";

import { Alert, Card, Spinner, cx, formatDate } from "../../components/ui";
import { errorMessage, retrainingApi } from "../../services/api";
import type { RetrainingStatus } from "../../services/types";

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

  return (
    <div className="space-y-5">
      <div>
        <h1 className="page-title">재학습 현황</h1>
        <p className="text-sm text-slate-500">
          상담원이 문의 상세에서 [분류 고치기]로 바로잡은 분류는 다음 모델의 학습 데이터가 됩니다.
          자주 고치는 패턴이 곧 모델의 약점입니다 (docs/retraining.md).
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="지금 쓰는 모델" value={<span className="font-mono text-base">{model.version}</span>}
          sub={model.trained_at ? `${formatDate(model.trained_at)} 학습 · 수정 ${model.corrections_used ?? 0}건 반영` : undefined} />
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
              <tr>{["버전", "베이스", "학습 데이터", "외부 테스트", "직접 쓴 평가용", "새 평가용 (2차)", "실전 100", "메모"].map((h) => <th key={h} className="px-2 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-hairline">
              {history.map((v) => (
                <tr key={v.version} className={cx("align-top", v.current && "bg-primary-soft/50")}>
                  <td className="whitespace-nowrap px-2 py-2 font-mono text-sm">
                    {v.version}{v.current && <span className="ml-1 rounded-full bg-primary px-2 py-0.5 font-sans text-white">사용 중</span>}
                  </td>
                  <td className="px-2 py-2">{v.base_model ?? "-"}</td>
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

      <Card title="재학습하는 방법">
        <p className="mb-3 text-sm text-slate-500">GPU가 필요하고 시간이 걸려 화면 버튼 대신 서버에서 명령으로 실행합니다.</p>
        <ol className="space-y-3 text-sm">
          {STEPS.map(([title, cmd], i) => (
            <li key={i}>
              <p className="font-medium text-ink">{i + 1}. {title}</p>
              {cmd && <pre className="mt-1 overflow-x-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">{cmd}</pre>}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}
