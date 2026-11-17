// 고객 문의 폼 (/inquiry): 등록하면 그 자리에서 자동 답변 또는 접수 안내를 보여 줍니다 (동기 방식).
import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { Bubble, Note, Thumbs } from "../../components/Chat";
import FaqSuggestions from "../../components/FaqSuggestions";
import PhotoPicker, { type PickedPhoto } from "../../components/PhotoPicker";
import { Alert, Button, Card, Field, Input, Spinner, Textarea, cx } from "../../components/ui";
import { customerApi, errorMessage } from "../../services/api";
import type { InquiryCreated } from "../../services/types";

const EMPTY = { customer_name: "", customer_email: "", order_number: "", title: "", content: "", password: "", password2: "" };
// 주문과 관련된 문의로 보이는 표현 (주문번호 입력 권유용, 판단이 틀려도 입력은 선택이라 영향 없음)
const ORDER_WORDS = /배송|택배|송장|도착|못\s?받|안\s?와|출고|주문|취소|교환|반품|환불|파손|누락|오배송|불량|사이즈/;
const WAIT_MESSAGES = ["문의 내용을 분석하고 있습니다…", "답변을 작성하고 있습니다…", "조금만 기다려 주세요…"];

export default function InquiryFormPage() {
  const [form, setForm] = useState(EMPTY);
  const [sending, setSending] = useState(false);
  const [waitStep, setWaitStep] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState<InquiryCreated | null>(null);
  const [lookupEmail, setLookupEmail] = useState("");
  const [sentAt, setSentAt] = useState<string | null>(null);
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [agreed, setAgreed] = useState(false);

  useEffect(() => {
    if (!sending) return;
    setWaitStep(0);
    const timer = setInterval(() => setWaitStep((s) => Math.min(s + 1, WAIT_MESSAGES.length - 1)), 4000);
    return () => clearInterval(timer);
  }, [sending]);

  const needsOrder = !form.order_number.trim() && ORDER_WORDS.test(`${form.title} ${form.content}`);
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
      setResult(await customerApi.create({ ...body, order_number: form.order_number.trim() || null,
        privacy_agreed: agreed, attachment_tokens: photos.map((p) => p.token) }));
      setLookupEmail(form.customer_email);
      setSentAt(new Date().toISOString());
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
          {/* 대화형: 내가 보낸 문의(오른쪽) → AI 답변 또는 접수 안내(왼쪽) */}
          <div className="space-y-4 rounded-xl bg-slate-50 p-4">
            <Bubble side="right" tone="customer" name="나" at={sentAt}
              footer={<Thumbs photos={photos.map((p) => ({ url: p.preview, filename: p.name }))} />}>{form.content}</Bubble>
            {result.answer
              ? <Bubble side="left" tone="ai" name="AI 상담원" at={sentAt}>{result.answer}</Bubble>
              : <Note>{result.message}</Note>}
          </div>
          {result.answer && <p className="mt-3 text-xs text-slate-500">{result.message}</p>}
        </Card>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => { setResult(null); setForm(EMPTY); setPhotos([]); setAgreed(false); }}>새 문의 작성</Button>
          {/* 이메일은 주소(URL)에 남기지 않고 화면 이동 상태로만 넘김 */}
          <Link to="/inquiry/lookup" state={{ email: lookupEmail }}
            className="inline-flex min-h-11 items-center rounded-xl border border-hairline bg-canvas px-5 py-2.5 text-sm font-semibold text-ink hover:bg-surface-card">
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

        <Field label="제목">
          <Input required maxLength={200} value={form.title} onChange={set("title")} disabled={sending} />
        </Field>
        <Field label="문의 내용" hint={`${form.content.length} / 2,000자 (5자 이상)`}>
          <Textarea required minLength={5} maxLength={2000} value={form.content} onChange={set("content")} disabled={sending} />
        </Field>
        {/* 주문번호는 선택. 주문 관련 내용(배송·취소·교환·반품 등)을 쓰면 칸을 강조해 입력을 권유 */}
        <Field label="주문번호 (선택)"
          hint={needsOrder ? "주문 관련 문의 같아요. 주문번호를 적어 주시면 주문을 바로 확인해 더 빨리 처리해 드려요. 예: 20261103-0042"
            : "주문 관련 문의라면 입력해 주세요. 마이페이지 > 주문내역에서 확인할 수 있어요. 예: 20261103-0042"}>
          <Input maxLength={30} value={form.order_number} onChange={set("order_number")} disabled={sending}
            className={cx(needsOrder && "border-amber-400 bg-amber-50/50 ring-2 ring-amber-100")} />
        </Field>
        <div className="space-y-1">
          <span className="text-sm font-medium text-slate-700">사진 첨부 (선택)</span>
          <PhotoPicker value={photos} onChange={setPhotos} disabled={sending} />
          <span className="block text-xs text-slate-500">불량·파손·오배송이라면 사진을 올려 주시면 더 빨리 확인할 수 있어요. JPG·PNG·WEBP, 한 장 5MB, 3장까지</span>
        </div>
        {!sending && <FaqSuggestions text={`${form.title} ${form.content}`} />}

        {/* 개인정보 수집·이용 동의 (비회원 문의라 이름·이메일을 받으므로 필수) */}
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">
          <p className="mb-1 font-medium text-slate-800">개인정보 수집·이용 안내</p>
          <ul className="list-disc space-y-0.5 pl-4">
            <li>수집 항목: 이름, 이메일, 주문번호(선택), 문의 내용, 첨부 사진(선택)</li>
            <li>이용 목적: 문의 확인·답변, 주문 확인, 답변 알림</li>
            <li>보관 기간: 문의 처리 후 3년 (전자상거래법의 소비자 불만·분쟁 처리 기록 보존 기간)</li>
            <li>문의 내용은 빠른 답변을 위해 AI 분석에 쓰이며, 외부 AI 서비스(OpenAI)에서 처리될 수 있습니다.</li>
            <li>AI 답변 품질 점검을 위해 처리 기록이 외부 서비스(LangSmith)에 보관될 수 있으며, 이때 이메일·전화번호·주문번호 등은 가려서 보냅니다.</li>
            <li>동의하지 않으실 수 있으나, 동의하지 않으면 1:1 문의를 등록할 수 없습니다.</li>
          </ul>
          <label className="mt-2 flex items-center gap-2 text-sm text-slate-800">
            <input type="checkbox" required checked={agreed} onChange={(e) => setAgreed(e.target.checked)} disabled={sending} />
            개인정보 수집·이용에 동의합니다 (필수)
          </label>
        </div>
        {error && <Alert>{error}</Alert>}
        <Button type="submit" disabled={sending} className="w-full py-2.5">
          {sending ? <span className="inline-flex items-center gap-2"><Spinner />{WAIT_MESSAGES[waitStep]}</span> : "문의 등록"}
        </Button>
        {sending ? <p className="text-center text-xs text-slate-500">자동 답변을 작성하는 경우 10초 정도 걸릴 수 있습니다.</p>
          : <p className="text-center text-xs text-slate-500">자주 묻는 질문은 바로 답변드리고, 담당자 확인이 필요한 문의는 영업일 기준 1일 이내(평일 10:00~17:00)에 답변드려요.</p>}
      </form>
    </Card>
  );
}
