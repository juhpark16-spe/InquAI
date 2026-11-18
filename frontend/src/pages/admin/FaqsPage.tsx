// FAQ 관리 (/admin/faqs, 관리자만): FAQ 목록·검색, 등록, 수정, 비활성·다시 활성, 검색 미리 보기
// FAQ는 AI 자동 답변의 유일한 근거라, 저장하면 서버가 검색 색인을 바로 다시 만들어 에이전트·고객 추천에 반영됩니다.
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import Icon from "../../components/Icon";
import { Alert, Button, Card, Field, Input, Select, Spinner, Textarea, cx, formatDate } from "../../components/ui";
import { errorMessage, faqApi, type FaqInput } from "../../services/api";
import { CATEGORIES, type FaqAdmin, type FaqSearchTest } from "../../services/types";

const EMPTY: FaqInput = { category: "배송", question: "", answer: "" };
const ANSWER_MAX = 1000;

/** 유형·질문·답변 입력 (등록·수정 같이 씀) */
function FaqFields({ value, onChange, disabled }: { value: FaqInput; onChange: (v: FaqInput) => void; disabled?: boolean }) {
  return (
    <div className="space-y-3">
      <Field label="유형">
        <Select className="w-full" disabled={disabled} value={value.category} onChange={(e) => onChange({ ...value, category: e.target.value })}>
          {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
        </Select>
      </Field>
      <Field label="질문" hint="고객이 실제로 물어볼 말투로 적으면 검색이 잘 됩니다. 5~200자">
        <Input required minLength={5} maxLength={200} disabled={disabled} value={value.question}
          onChange={(e) => onChange({ ...value, question: e.target.value })} />
      </Field>
      <Field label={`답변 (${value.answer.length}/${ANSWER_MAX})`}
        hint="AI 자동 답변은 이 내용만 근거로 씁니다. 쇼핑몰 정책(docs/shop_policy.md)과 맞는지 확인해 주세요.">
        <Textarea required minLength={10} maxLength={ANSWER_MAX} disabled={disabled} value={value.answer}
          onChange={(e) => onChange({ ...value, answer: e.target.value })} />
      </Field>
    </div>
  );
}

function CreateForm({ onCreated }: { onCreated: (f: FaqAdmin) => void }) {
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const f = await faqApi.create(form);
      setForm({ ...EMPTY, category: form.category });
      onCreated(f);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="새 FAQ 등록">
      <form onSubmit={submit} className="space-y-3">
        <FaqFields value={form} onChange={setForm} disabled={busy} />
        <p className="text-xs text-slate-500">번호는 자동으로 붙습니다 (다음 번호).</p>
        {error && <Alert>{error}</Alert>}
        <Button type="submit" disabled={busy} className="w-full">{busy ? <Spinner /> : "등록"}</Button>
      </form>
    </Card>
  );
}

/** 이 질문이면 어떤 FAQ가 검색되는지 (에이전트·고객 추천과 같은 검색) */
function SearchPreview({ version }: { version: number }) {
  const [q, setQ] = useState("");
  const [result, setResult] = useState<FaqSearchTest | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(text: string) {
    if (text.trim().length < 2) return;
    setError("");
    setBusy(true);
    try {
      setResult(await faqApi.searchTest(text.trim()));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  // FAQ를 저장하면 같은 질문으로 다시 검색해 바뀐 결과를 보여 줌
  useEffect(() => { if (version && q.trim().length >= 2) run(q); }, [version]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Card title="검색 미리 보기">
      <p className="mb-3 text-sm text-slate-500">고객 문의처럼 적어 보면, AI가 근거로 찾을 FAQ와 유사도를 보여 줍니다.</p>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); run(q); }}>
        <Input placeholder="예: 반품하면 배송비 얼마예요?" value={q} onChange={(e) => setQ(e.target.value)} />
        <Button type="submit" disabled={busy || q.trim().length < 2} aria-label="검색"><Icon name="search" /></Button>
      </form>
      {error && <div className="mt-3"><Alert>{error}</Alert></div>}
      {result && (
        <div className="mt-3 space-y-2">
          {result.hits.length === 0 && <p className="text-sm text-slate-500">검색된 FAQ가 없습니다.</p>}
          {result.hits.map((h, i) => (
            <div key={h.code} className="rounded-xl border border-hairline p-3">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="font-mono text-slate-500">{i + 1}. {h.code} · {h.category}</span>
                <span className={cx("rounded-full px-2 py-0.5 font-medium", h.suggested ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500")}>
                  {h.suggested ? "고객 추천됨" : "추천 기준 미만"}
                </span>
              </div>
              <p className="mt-1 text-sm text-ink">{h.question}</p>
              <div className="mt-2 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                  <div className={cx("h-full rounded-full", h.suggested ? "bg-primary" : "bg-slate-300")}
                    style={{ width: `${Math.max(0, Math.min(1, h.score)) * 100}%` }} />
                </div>
                <span className="w-10 text-right text-xs tabular-nums text-slate-500">{h.score.toFixed(2)}</span>
              </div>
            </div>
          ))}
          {result.engine && (
            <p className="text-xs text-slate-500">
              검색 방식 {result.engine === "kure" ? "KURE-v1 (뜻으로 찾기)" : "TF-IDF (글자로 찾기)"} · 고객 화면 추천 기준 {result.suggest_min_score}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

function FaqRow({ f, onChanged }: { f: FaqAdmin; onChanged: (msg: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<FaqInput>({ category: f.category, question: f.question, answer: f.answer });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function run(action: () => Promise<unknown>, msg: string) {
    setError("");
    setBusy(true);
    try {
      await action();
      setEditing(false);
      onChanged(msg);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className={cx("p-4", !f.is_active && "bg-slate-50")}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-mono font-semibold text-slate-500">{f.code}</span>
            <span className="rounded-full bg-primary-soft px-2 py-0.5 text-primary">{f.category}</span>
            {!f.is_active && <span className="rounded-full bg-slate-200 px-2 py-0.5 text-slate-500">비활성</span>}
            <span className="text-slate-400">수정 {formatDate(f.updated_at)}</span>
          </div>
          <button className={cx("mt-1 block text-left text-sm font-semibold hover:underline", f.is_active ? "text-ink" : "text-slate-400")}
            onClick={() => setOpen(!open)} aria-expanded={open}>
            {f.question}
          </button>
          {!editing && (
            <p className={cx("mt-1 whitespace-pre-line text-sm", f.is_active ? "text-body" : "text-slate-400", !open && "line-clamp-2")}>
              {f.answer}
            </p>
          )}
        </div>
        <div className="text-right text-xs text-slate-500" title="AI 자동 답변·초안의 근거로 쓰인 횟수">
          <div className="text-base font-semibold tabular-nums text-ink">{f.used_count}</div>
          <div>근거로 쓰임</div>
          {f.last_used_at && <div className="mt-0.5 text-slate-400">최근 {formatDate(f.last_used_at)}</div>}
        </div>
      </div>

      {editing ? (
        <form className="mt-3 space-y-3 rounded-xl border border-hairline bg-white p-4"
          onSubmit={(e) => { e.preventDefault(); run(() => faqApi.update(f.id, { ...form, is_active: f.is_active }), `${f.code}를 수정했습니다.`); }}>
          <FaqFields value={form} onChange={setForm} disabled={busy} />
          {f.used_count > 0 && (
            <Alert kind="info">이 FAQ는 AI 답변의 근거로 {f.used_count}번 쓰였습니다. 이미 보낸 답변은 바뀌지 않고, 앞으로의 답변부터 새 내용을 씁니다.</Alert>
          )}
          <div className="flex gap-2">
            <Button type="submit" disabled={busy}>{busy ? <Spinner /> : "저장"}</Button>
            <Button type="button" variant="ghost" disabled={busy}
              onClick={() => { setEditing(false); setForm({ category: f.category, question: f.question, answer: f.answer }); }}>취소</Button>
          </div>
        </form>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={busy} onClick={() => setEditing(true)}>수정</Button>
          {f.is_active ? (
            <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={busy}
              onClick={() => {
                if (!window.confirm(`${f.code} "${f.question}"을(를) 비활성화할까요?\n고객 FAQ 화면과 AI 검색에서 빠집니다. 다시 활성화할 수 있습니다.`)) return;
                run(() => faqApi.deactivate(f.id), `${f.code}를 비활성화했습니다. 고객 화면과 AI 검색에서 빠졌습니다.`);
              }}>
              비활성화
            </Button>
          ) : (
            <Button className="min-h-9 px-3 py-1" disabled={busy}
              onClick={() => run(() => faqApi.update(f.id, { category: f.category, question: f.question, answer: f.answer, is_active: true }),
                `${f.code}를 다시 활성화했습니다.`)}>
              다시 활성화
            </Button>
          )}
        </div>
      )}
      {error && <div className="mt-2"><Alert>{error}</Alert></div>}
    </li>
  );
}

export default function FaqsPage() {
  const [faqs, setFaqs] = useState<FaqAdmin[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [version, setVersion] = useState(0);   // 저장할 때마다 올림 → 검색 미리 보기 새로 고침

  const load = useCallback(() => {
    faqApi.list().then(setFaqs).catch((err) => setError(errorMessage(err)));
  }, []);
  useEffect(load, [load]);

  const changed = (msg: string) => { setNotice(msg); setVersion((v) => v + 1); load(); };

  const shown = useMemo(() => {
    const word = q.trim().toLowerCase();
    return (faqs ?? []).filter((f) => (showInactive || f.is_active) && (!category || f.category === category)
      && (!word || `${f.code} ${f.question} ${f.answer}`.toLowerCase().includes(word)));
  }, [faqs, category, q, showInactive]);

  const active = faqs?.filter((f) => f.is_active) ?? [];
  const counts = useMemo(() => Object.fromEntries(CATEGORIES.map((c) => [c, active.filter((f) => f.category === c).length])), [active]);
  const inactiveCount = (faqs?.length ?? 0) - active.length;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">FAQ 관리</h1>
        <p className="text-sm text-slate-500">
          FAQ는 고객 FAQ 화면, 문의 작성 중 추천, <b className="font-medium text-slate-700">AI 자동 답변의 근거</b>로 쓰입니다.
          저장하면 바로 검색에 반영됩니다. 지우지 않고 비활성화하므로 지난 답변의 근거 기록은 남습니다.
        </p>
      </div>
      {error && <Alert>{error}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="min-w-0 rounded-2xl border border-hairline bg-white">
          <div className="space-y-3 border-b border-hairline p-4">
            <div className="flex flex-wrap gap-1.5">
              {["", ...CATEGORIES].map((c) => (
                <button key={c || "all"} type="button" onClick={() => setCategory(c)} aria-pressed={category === c}
                  className={cx("rounded-full border px-3 py-1 text-xs",
                    category === c ? "border-primary bg-primary text-white" : "border-hairline bg-white text-body hover:border-slate-400")}>
                  {c || "전체"} <span className="tabular-nums opacity-70">{c ? counts[c] : active.length}</span>
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <div className="min-w-48 flex-1">
                <Input placeholder="번호·질문·답변으로 찾기" value={q} onChange={(e) => setQ(e.target.value)} aria-label="FAQ 찾기" />
              </div>
              <label className="flex items-center gap-2 text-sm text-body">
                <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
                비활성 FAQ도 보기 ({inactiveCount})
              </label>
            </div>
          </div>
          {!faqs && !error && <p className="p-6 text-center text-slate-500"><Spinner /></p>}
          {faqs && shown.length === 0 && <p className="p-6 text-center text-sm text-slate-500">조건에 맞는 FAQ가 없습니다.</p>}
          <ul className="divide-y divide-hairline">
            {shown.map((f) => <FaqRow key={`${f.id}-${f.updated_at}-${f.is_active}`} f={f} onChanged={changed} />)}
          </ul>
          <p className="border-t border-hairline px-4 py-2 text-xs text-slate-500">
            활성 {active.length}개 · 비활성 {inactiveCount}개 · AI 근거로 한 번도 안 쓰인 활성 FAQ {active.filter((f) => !f.used_count).length}개
          </p>
        </div>

        <div className="space-y-4">
          <CreateForm onCreated={(f) => changed(`${f.code} "${f.question}"을(를) 등록했습니다. 바로 검색됩니다.`)} />
          <SearchPreview version={version} />
        </div>
      </div>
    </div>
  );
}
