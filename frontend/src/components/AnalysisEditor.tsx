// AI 분석 카드 안의 "분류 고치기": 상담원이 유형·감정을 고치면 재학습 데이터로 저장
// (PATCH /api/inquiries/{id}/analysis). 유형·감정이 바뀌면 처리 경로·긴급도(답변 기한)는 서버가 규칙으로 다시 계산
import { useState } from "react";

import { errorMessage, inquiryApi } from "../services/api";
import { CATEGORIES, SENTIMENTS, type InquiryDetail } from "../services/types";
import { Alert, Button, Select, Spinner } from "./ui";

type Field = "category" | "sentiment";
const NAMES: Record<Field, string> = { category: "유형", sentiment: "감정" };

/** 처음 AI가 고른 라벨 (고친 적이 있으면 첫 수정의 before) */
export function originalLabel(d: InquiryDetail, field: Field): string | null {
  return d.corrections.find((c) => c.field === field)?.before_label ?? null;
}

export default function AnalysisEditor({ data, onSaved }: { data: InquiryDetail; onSaved: () => void }) {
  const a = data.analysis!;
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState(a.category);
  const [sentiment, setSentiment] = useState(a.sentiment);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const changed: { category?: string; sentiment?: string } = {
    ...(category !== a.category ? { category } : {}),
    ...(sentiment !== a.sentiment ? { sentiment } : {}),
  };

  async function save() {
    setError("");
    setBusy(true);
    try {
      await inquiryApi.correctAnalysis(data.id, changed);
      setOpen(false);
      onSaved();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const fixed = (["category", "sentiment"] as Field[])
    .map((f) => [f, originalLabel(data, f)] as const)
    .filter(([f, orig]) => orig !== null && orig !== a[f]);

  if (!open) {
    return (
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm text-slate-600">
          {fixed.length > 0
            ? fixed.map(([f, orig]) => `${NAMES[f]}: AI ${orig} → 상담원 ${a[f]}`).join(" · ")
            : "AI가 잘못 고른 분류는 고쳐 주세요 (재학습에 씁니다)"}
        </span>
        <Button variant="ghost" className="min-h-0 px-3 py-1.5 text-sm" onClick={() => {
          setCategory(a.category);
          setSentiment(a.sentiment);
          setOpen(true);
        }}>분류 고치기</Button>
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-2 rounded-xl border border-indigo-200 bg-indigo-50/40 p-3">
      <div className="grid grid-cols-[3rem_1fr] items-center gap-2 text-base">
        <span className="text-slate-600">유형</span>
        <Select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="유형">
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}{c === a.category ? " (지금)" : ""}</option>)}
        </Select>
        <span className="text-slate-600">감정</span>
        <Select value={sentiment} onChange={(e) => setSentiment(e.target.value)} aria-label="감정">
          {SENTIMENTS.map((s) => <option key={s} value={s}>{s}{s === a.sentiment ? " (지금)" : ""}</option>)}
        </Select>
      </div>
      <p className="text-sm text-slate-600">
        저장하면 재학습 데이터로 남고, 처리 경로·긴급도(답변 기한)가 규칙으로 다시 정해집니다. 답변은 다시 만들지 않습니다.
      </p>
      {error && <Alert>{error}</Alert>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" className="min-h-0 px-3 py-1.5 text-sm" onClick={() => setOpen(false)} disabled={busy}>취소</Button>
        <Button className="min-h-0 px-3 py-1.5 text-sm" onClick={save} disabled={busy || Object.keys(changed).length === 0}>
          {busy ? <Spinner /> : "저장"}
        </Button>
      </div>
    </div>
  );
}
