// 고객 문의 폼 (/inquiry): 등록하면 그 자리에서 자동 답변 또는 접수 안내를 보여 줍니다 (동기 방식).
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";

import FaqSuggestions from "../../components/FaqSuggestions";
import { Alert, Button, Card, Field, Input, Spinner, Textarea } from "../../components/ui";
import { customerApi, errorMessage } from "../../services/api";
import type { InquiryCreated } from "../../services/types";

const EMPTY = { customer_name: "", customer_email: "", order_number: "", title: "", content: "", password: "", password2: "" };
const WAIT_MESSAGES = ["문의 내용을 분석하고 있습니다…", "답변을 작성하고 있습니다…", "조금만 기다려 주세요…"];

export default function InquiryFormPage() {
  const [form, setForm] = useState(EMPTY);
  const [sending, setSending] = useState(false);
  const [waitStep, setWaitStep] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState<InquiryCreated | null>(null);
  const [lookupEmail, setLookupEmail] = useState("");

  useEffect(() => {
    if (!sending) return;
    setWaitStep(0);
    const timer = setInterval(() => setWaitStep((s) => Math.min(s + 1, WAIT_MESSAGES.length - 1)), 4000);
    return () => clearInterval(timer);
  }, [sending]);

  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (form.password !== form.password2) {
      setError("비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    setSending(true);
    try {
      const { password2: _, ...body } = form;
      setResult(await customerApi.create({ ...body, order_number: form.order_number.trim() || null }));
      setLookupEmail(form.customer_email);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSending(false);
    }
  }

  if (result) {
    return (
      <div className="space-y-4">
        <Card title="문의가 등록되었습니다">
          <dl className="mb-4 grid grid-cols-[6rem_1fr] gap-y-1 text-sm">
            <dt className="text-slate-500">문의 번호</dt>
            <dd className="font-mono font-semibold text-slate-900">{result.inquiry_number}</dd>
            <dt className="text-slate-500">처리 상태</dt>
            <dd>{result.status}</dd>
          </dl>
          {result.answer ? (
            <div className="space-y-2">
              <p className="text-sm font-medium text-emerald-700">AI 상담원 답변</p>
              <p className="whitespace-pre-line rounded-lg bg-emerald-50 p-4 text-sm leading-relaxed text-slate-800">{result.answer}</p>
            </div>
          ) : (
            <Alert kind="info">{result.message}</Alert>
          )}
          {result.answer && <p className="mt-3 text-xs text-slate-500">{result.message}</p>}
        </Card>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => { setResult(null); setForm(EMPTY); }}>새 문의 작성</Button>
          {/* 이메일은 주소(URL)에 남기지 않고 화면 이동 상태로만 넘김 */}
          <Link to="/inquiry/lookup" state={{ email: lookupEmail }}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 hover:bg-slate-50">
            문의 조회로 이동
          </Link>
        </div>
      </div>
    );
  }

  return (
    <Card title="1:1 문의하기">
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="이름">
            <Input required maxLength={50} value={form.customer_name} onChange={set("customer_name")} disabled={sending} />
          </Field>
          <Field label="이메일" hint="문의 조회와 주문 확인에 사용합니다.">
            <Input required type="email" maxLength={255} value={form.customer_email} onChange={set("customer_email")} disabled={sending} />
          </Field>
          <Field label="조회 비밀번호" hint="6자 이상. 이메일과 함께 입력하면 내 문의를 볼 수 있어요.">
            <Input required type="password" minLength={6} maxLength={64} autoComplete="new-password"
              value={form.password} onChange={set("password")} disabled={sending} />
          </Field>
          <Field label="비밀번호 확인" hint="비밀번호는 찾을 수 없으니 기억하기 쉬운 것으로 정해 주세요.">
            <Input required type="password" minLength={6} maxLength={64} autoComplete="new-password"
              value={form.password2} onChange={set("password2")} disabled={sending} />
          </Field>
        </div>
        <Field label="주문번호 (선택)" hint="주문 관련 문의라면 입력해 주세요. 예: 20261103-0042">
          <Input maxLength={30} value={form.order_number} onChange={set("order_number")} disabled={sending} />
        </Field>
        <Field label="제목">
          <Input required maxLength={200} value={form.title} onChange={set("title")} disabled={sending} />
        </Field>
        <Field label="문의 내용" hint={`${form.content.length} / 2,000자 (5자 이상)`}>
          <Textarea required minLength={5} maxLength={2000} value={form.content} onChange={set("content")} disabled={sending} />
        </Field>
        {!sending && <FaqSuggestions text={`${form.title} ${form.content}`} />}
        {error && <Alert>{error}</Alert>}
        <Button type="submit" disabled={sending} className="w-full py-2.5">
          {sending ? <span className="inline-flex items-center gap-2"><Spinner />{WAIT_MESSAGES[waitStep]}</span> : "문의 등록"}
        </Button>
        {sending && <p className="text-center text-xs text-slate-500">자동 답변을 작성하는 경우 10초 정도 걸릴 수 있습니다.</p>}
      </form>
    </Card>
  );
}
