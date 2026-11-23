// 고객의 문의를 대화형으로 보여 주고(내 글 = 오른쪽, 고객센터 = 왼쪽) 답변 평가·추가 문의를 받음.
// 비회원 조회(/inquiry/lookup, 이메일 + 조회 비밀번호)와 쇼핑몰 로그인 고객(/my)이 함께 씀: 서버 호출만 actions로 넘김
// 여러 건이면 요약 카드로 접어 두고(제목·답변 상태·마지막 글 한 줄) 가장 최근 문의만 펼침. 상태는 고객 말로(답변 준비 중 / 답변 완료)
import { useState } from "react";

import { Bubble, Note, Thumbs } from "./Chat";
import PhotoPicker, { type PickedPhoto } from "./PhotoPicker";
import { Alert, Button, Input, Spinner, Textarea, cx, formatDate } from "./ui";
import { errorMessage } from "../services/api";
import type { InquiryPublic } from "../services/types";

export interface ThreadActions {
  rate: (inquiryNumber: string, answerId: number, helpful: boolean) => Promise<unknown>;
  followUp: (inquiryNumber: string, content: string, tokens: string[], orderNumber?: string | null) => Promise<unknown>;
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

/** 주문번호: 공백 제거, 12자리 숫자면 8-4 로 (문의하기 화면·서버와 같은 규칙). 형식이 맞으면 번호, 빈칸 "", 틀리면 null */
function normalizeOrder(raw: string): string | null {
  const v = raw.replace(/\s/g, "");
  if (!v) return "";
  const fixed = /^\d{12}$/.test(v) ? `${v.slice(0, 8)}-${v.slice(8)}` : v;
  return /^\d{8}-\d{4}$/.test(fixed) ? fixed : null;
}

/** 내용 보충 · 추가 문의: 문의 수정 대신 빠뜨린 내용·사진·주문번호를 이어서 보냄 (처음 글은 그대로 남음) */
function FollowUp({ inquiry, actions, onDone }: { inquiry: InquiryPublic; actions: ThreadActions; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [order, setOrder] = useState("");
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!inquiry.can_follow_up) return <p className="text-xs text-slate-500">이 문의에는 더 이상 추가 문의를 남길 수 없어요. 새 문의로 남겨 주세요.</p>;
  if (!open) return <Button variant="ghost" onClick={() => setOpen(true)}>내용 보충 · 추가 문의</Button>;
  // 주문번호가 없거나, 적은 번호로 내 주문을 찾지 못했으면 다시 받음
  const needsOrder = !inquiry.order_number || !!inquiry.order_needs_fix;
  const orderNumber = needsOrder ? normalizeOrder(order) : "";
  const orderError = needsOrder && orderNumber === null && order.replace(/\s/g, "").length >= 8
    ? "주문번호는 20261103-0042처럼 숫자 8자리-4자리예요." : "";

  async function send() {
    setError("");
    setBusy(true);
    try {
      await actions.followUp(inquiry.inquiry_number, text, photos.map((p) => p.token), orderNumber || null);
      setText("");
      setOrder("");
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
      <p className="text-xs text-muted">등록한 문의는 고칠 수 없어요. 빠뜨린 내용·사진은 여기에 이어서 보내 주세요.</p>
      {inquiry.photos_requested && (
        <p className="rounded-lg bg-primary-soft px-3 py-2 text-sm text-ink">📷 <b>송장이 보이는 사진 1장</b>과 <b>파손 부위 사진 1장</b>을 함께 올려 주세요. 사진이 오면 바로 확인해 드려요.</p>
      )}
      <Textarea value={text} onChange={(e) => setText(e.target.value)} maxLength={2000} className="min-h-24"
        placeholder="더 궁금한 점, 빠뜨린 내용, 해결되지 않은 내용을 적어 주세요." disabled={busy} />
      {needsOrder && (
        <label className="block space-y-1 text-sm">
          <span className="font-semibold text-ink">주문번호 (선택)</span>
          <Input value={order} onChange={(e) => setOrder(e.target.value)} maxLength={30} inputMode="numeric" placeholder="20261103-0042"
            disabled={busy} aria-invalid={!!orderError} className={cx(orderError && "border-rose-400 ring-2 ring-rose-100")}
            onBlur={() => { if (orderNumber) setOrder(orderNumber); }} />
          {orderError ? <span role="alert" className="block text-xs font-medium text-rose-600">{orderError}</span>
            : <span className="block text-xs text-muted">{inquiry.order_number
              ? `처음 적은 주문번호(${inquiry.order_number})로 주문을 찾지 못했어요. 맞는 번호를 적어 주세요.`
              : "처음 문의에 주문번호가 없어요. 주문 관련 문의라면 적어 주세요."} 바로 주문을 확인해 드려요.</span>}
        </label>
      )}
      <PhotoPicker value={photos} onChange={setPhotos} disabled={busy} />
      {error && <Alert>{error}</Alert>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>취소</Button>
        <Button onClick={send} disabled={busy || text.trim().length < 2 || orderNumber === null}>{busy ? <Spinner /> : "보내기"}</Button>
      </div>
    </div>
  );
}

/** 고객에게 보이는 상태: 내부 상태 이름(담당자 처리·자동 처리 등) 대신, 마지막 글이 누구 것인지로.
 *  상담원이 '확인 후 다시 안내'를 표시해 두었으면 답변을 받았어도 '추가 안내 예정' */
function CustomerStatus({ waiting, more }: { waiting: boolean; more: boolean }) {
  if (waiting) return <span className="whitespace-nowrap rounded-full bg-primary-soft px-2.5 py-0.5 text-xs font-semibold text-primary">답변 준비 중</span>;
  if (more) return <span className="whitespace-nowrap rounded-full bg-primary-soft px-2.5 py-0.5 text-xs font-semibold text-primary">추가 안내 예정</span>;
  return <span className="whitespace-nowrap rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">답변 완료</span>;
}

export default function InquiryThreads({ items, notice, actions, reload }: {
  items: InquiryPublic[]; notice: string; actions: ThreadActions; reload: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [done, setDone] = useState("");
  // 문의가 여러 건이면 길어지므로 접어 두고, 가장 최근 문의 하나만 펼침
  const [open, setOpen] = useState<Set<string>>(() => new Set(items.slice(0, 1).map((i) => i.inquiry_number)));
  const toggle = (n: string) => setOpen((prev) => {
    const next = new Set(prev);
    if (next.has(n)) next.delete(n); else next.add(n);
    return next;
  });

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
    <div className="space-y-3">
      {error && <Alert>{error}</Alert>}
      {done && <Alert kind="success">{done}</Alert>}
      {items.map((found) => {
        // 내 글(처음 문의 + 추가 문의)과 고객센터 답변을 시간순으로
        const thread = [
          { kind: "me" as const, at: found.created_at, text: found.content, messageId: null as number | null },
          ...found.messages.map((m) => ({ kind: "me" as const, at: m.at, text: m.text, messageId: m.id as number | null })),
          ...found.answers.map((a) => ({ kind: "answer" as const, at: a.answered_at, text: a.text, a })),
        ].sort((x, y) => new Date(x.at).getTime() - new Date(y.at).getTime());
        const last = thread[thread.length - 1];
        const waiting = last.kind === "me";
        const isOpen = open.has(found.inquiry_number);
        return (
          <section key={found.inquiry_number} className="overflow-hidden rounded-2xl border border-hairline bg-white">
            <button type="button" onClick={() => toggle(found.inquiry_number)} aria-expanded={isOpen}
              className={cx("flex w-full items-start gap-3 px-5 py-4 text-left hover:bg-surface-soft", isOpen && "border-b border-hairline")}>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-base font-semibold text-ink">{found.title}</span>
                  <CustomerStatus waiting={waiting} more={!!found.more_answer_coming} />
                </span>
                <span className="mt-0.5 block text-xs text-muted">{formatDate(found.created_at)} · <span className="font-mono">{found.inquiry_number}</span></span>
                {!isOpen && (
                  <span className="mt-1.5 block truncate text-sm text-body">
                    {last.kind === "answer" ? <b className="font-medium text-primary">{last.a.by}: </b> : "나: "}{last.text}
                  </span>
                )}
              </span>
              <span className="shrink-0 pt-0.5 text-sm text-muted">{isOpen ? "접기 ▴" : "펼치기 ▾"}</span>
            </button>
            {isOpen && (
              <div className="px-5 py-4">
                <div className="space-y-4 rounded-xl bg-surface-soft/70 p-4">
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
                  {!waiting && found.more_answer_coming && <Note>담당자가 확인한 뒤 이어서 안내해 드릴게요.</Note>}
                </div>
                <div className="mt-3">
                  <FollowUp inquiry={found} actions={actions}
                    onDone={() => { setDone("추가 문의가 접수되었습니다. 담당자가 확인 후 답변드릴게요."); reload(); }} />
                </div>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
