// 내 문의 조회 (/inquiry/lookup): 이메일 + 조회 비밀번호로 내 문의를 대화형으로 보고,
// 답변 평가(도움이 되었나요?)와 추가 문의를 남길 수 있음. 비밀번호는 이 화면 안에서만 기억(저장하지 않음)
import { useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router";

import { Bubble, Note, Thumbs } from "../../components/Chat";
import PhotoPicker, { type PickedPhoto } from "../../components/PhotoPicker";
import { Alert, Badge, Button, Card, Field, Input, Spinner, Textarea, cx, formatDate } from "../../components/ui";
import { customerApi, errorMessage } from "../../services/api";
import type { InquiryPublic } from "../../services/types";

function RateButtons({ answerId, rating, onRate }: { answerId: number; rating: number | null; onRate: (id: number, helpful: boolean) => void }) {
  const btn = (helpful: boolean, label: string) => {
    const on = rating === (helpful ? 1 : -1);
    return (
      <button type="button" onClick={() => onRate(answerId, helpful)} aria-pressed={on}
        className={cx("rounded-full border px-2 py-0.5", on ? (helpful ? "border-emerald-500 bg-emerald-50 text-emerald-700" : "border-rose-400 bg-rose-50 text-rose-700")
          : "border-slate-300 bg-white text-slate-500 hover:border-slate-400")}>
        {label}
      </button>
    );
  };
  return (
    <span className="flex items-center gap-1.5">
      <span>도움이 되었나요?</span>
      {btn(true, "👍 네")}
      {btn(false, "👎 아니요")}
    </span>
  );
}

function FollowUp({ inquiry, email, password, onDone }: { inquiry: InquiryPublic; email: string; password: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!inquiry.can_follow_up) return <p className="text-xs text-slate-500">이 문의에는 더 이상 추가 문의를 남길 수 없어요. 새 문의로 남겨 주세요.</p>;
  if (!open) return <Button variant="ghost" onClick={() => setOpen(true)}>추가 문의하기</Button>;

  async function send() {
    setError("");
    setBusy(true);
    try {
      await customerApi.followUp(email, password, inquiry.inquiry_number, text, photos.map((p) => p.token));
      setText("");
      setPhotos([]);
      setOpen(false);
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
      <Textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} className="min-h-24"
        placeholder="답변을 보고 더 궁금한 점이나 해결되지 않은 내용을 적어 주세요." disabled={busy} />
      <PhotoPicker value={photos} onChange={setPhotos} disabled={busy} />
      {error && <Alert>{error}</Alert>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>취소</Button>
        <Button onClick={send} disabled={busy || text.trim().length < 2}>{busy ? <Spinner /> : "추가 문의 보내기"}</Button>
      </div>
    </div>
  );
}

export default function InquiryLookupPage() {
  const fromForm = (useLocation().state as { email?: string } | null)?.email ?? "";
  const [email, setEmail] = useState(fromForm);
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [items, setItems] = useState<InquiryPublic[] | null>(null);
  const [notice, setNotice] = useState("");
  const [done, setDone] = useState("");

  async function load() {
    const r = await customerApi.lookup(email.trim(), password);
    setItems(r.items);
    setNotice(r.notice);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setDone("");
    setItems(null);
    setLoading(true);
    try {
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  async function rate(inquiryNumber: string, answerId: number, helpful: boolean) {
    try {
      await customerApi.rate(answerId, inquiryNumber, email.trim(), password, helpful);
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      <Card title="내 문의 조회">
        <form onSubmit={submit} className="space-y-4">
          <Field label="문의할 때 쓴 이메일">
            <Input required type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="조회 비밀번호" hint="문의할 때 정한 비밀번호입니다. 비밀번호가 다르게 작성된 문의는 따로 조회됩니다.">
            <Input required type="password" autoComplete="current-password" autoFocus={!!fromForm}
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {error && <Alert>{error}</Alert>}
          <Button type="submit" disabled={loading}>{loading ? <Spinner /> : "조회"}</Button>
        </form>
        <p className="mt-4 text-xs text-slate-500">
          비밀번호가 기억나지 않으면 <Link to="/inquiry" className="text-indigo-600 hover:underline">새 문의</Link>에
          이전 문의 내용을 함께 적어 주세요. 담당자가 확인해 드립니다.
        </p>
      </Card>

      {items && <p className="text-sm text-slate-600">문의 {items.length}건 (최신순) · {notice}</p>}
      {done && <Alert kind="success">{done}</Alert>}
      {items?.map((found) => {
        // 내 글(처음 문의 + 추가 문의)과 고객센터 답변을 시간순으로
        const thread = [
          { kind: "me" as const, at: found.created_at, text: found.content, messageId: null as number | null },
          ...found.messages.map((m) => ({ kind: "me" as const, at: m.at, text: m.text, messageId: m.id as number | null })),
          ...found.answers.map((a) => ({ kind: "answer" as const, at: a.answered_at, text: a.text, a })),
        ].sort((x, y) => new Date(x.at).getTime() - new Date(y.at).getTime());
        const waiting = thread[thread.length - 1].kind === "me";
        return (
          <Card key={found.inquiry_number} title={found.title}>
            <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-slate-500">
              <Badge value={found.status} />
              <span>{formatDate(found.created_at)}</span>
              <span className="font-mono text-xs">{found.inquiry_number}</span>

            </div>
            {/* 대화형: 나(고객) = 오른쪽, 고객센터 = 왼쪽 */}
            <div className="space-y-4 rounded-xl bg-slate-50 p-4">
              {thread.map((t, i) => t.kind === "me" ? (
                <Bubble key={i} side="right" tone="customer" name="나" at={t.at}
                  footer={<Thumbs photos={found.attachments.filter((p) => p.message_id === t.messageId)} />}>{t.text}</Bubble>
              ) : (
                <Bubble key={i} side="left" tone={t.a.by === "AI 상담원" ? "ai" : "agent"} name={t.a.by} at={t.at}
                  footer={<RateButtons answerId={t.a.id} rating={t.a.rating} onRate={(id, h) => rate(found.inquiry_number, id, h)} />}>
                  {t.text}
                </Bubble>
              ))}
              {waiting && <Note>담당자가 확인하고 있어요. {notice}</Note>}
            </div>
            <div className="mt-3">
              <FollowUp inquiry={found} email={email.trim()} password={password}
                onDone={() => { setDone("추가 문의가 접수되었습니다. 담당자가 확인 후 답변드릴게요."); load(); }} />
            </div>
          </Card>
        );
      })}
    </div>
  );
}
