// 고객의 문의를 대화형으로 보여 주고(내 글 = 오른쪽, 고객센터 = 왼쪽) 답변 평가·추가 문의를 받음.
// 비회원 조회(/inquiry/lookup, 이메일 + 조회 비밀번호)와 쇼핑몰 로그인 고객(/my)이 함께 씀: 서버 호출만 actions로 넘김
import { useState } from "react";

import { Bubble, Note, Thumbs } from "./Chat";
import PhotoPicker, { type PickedPhoto } from "./PhotoPicker";
import { Alert, Badge, Button, Card, Spinner, Textarea, cx, formatDate } from "./ui";
import { errorMessage } from "../services/api";
import type { InquiryPublic } from "../services/types";

export interface ThreadActions {
  rate: (inquiryNumber: string, answerId: number, helpful: boolean) => Promise<unknown>;
  followUp: (inquiryNumber: string, content: string, tokens: string[]) => Promise<unknown>;
}

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

function FollowUp({ inquiry, actions, onDone }: { inquiry: InquiryPublic; actions: ThreadActions; onDone: () => void }) {
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
      await actions.followUp(inquiry.inquiry_number, text, photos.map((p) => p.token));
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

export default function InquiryThreads({ items, notice, actions, reload }: {
  items: InquiryPublic[]; notice: string; actions: ThreadActions; reload: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  async function rate(inquiryNumber: string, answerId: number, helpful: boolean) {
    setError("");
    try {
      await actions.rate(inquiryNumber, answerId, helpful);
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-4">
      {error && <Alert>{error}</Alert>}
      {done && <Alert kind="success">{done}</Alert>}
      {items.map((found) => {
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
              <FollowUp inquiry={found} actions={actions}
                onDone={() => { setDone("추가 문의가 접수되었습니다. 담당자가 확인 후 답변드릴게요."); reload(); }} />
            </div>
          </Card>
        );
      })}
    </div>
  );
}
