// 고객의 문의를 대화형으로 보여 주고(내 글 = 오른쪽, 고객센터 = 왼쪽) 답변 평가·추가 문의를 받음.
// 비회원 조회(/inquiry/lookup, 이메일 + 조회 비밀번호)와 쇼핑몰 로그인 고객(/my)이 함께 씀: 서버 호출만 actions로 넘김
// 여러 건이면 요약 카드로 접어 두고(제목·답변 상태·마지막 글 한 줄) 가장 최근 문의만 펼침. 상태는 고객 말로(답변 준비 중 / 답변 완료)
import { useState } from "react";

import { Bubble, Note, Thumbs } from "./Chat";
import PhotoPicker, { type PickedPhoto } from "./PhotoPicker";
import { EMPTY_REFUND, REFUND_WORDS, RefundAccountToggle, refundValue } from "./RefundAccountFields";
import { Alert, Button, Input, Spinner, Textarea, cx, formatDate } from "./ui";
import { errorMessage } from "../services/api";
import type { InquiryPublic, RefundAccountInput } from "../services/types";

export interface ThreadActions {
  rate: (inquiryNumber: string, answerId: number, helpful: boolean) => Promise<unknown>;
  followUp: (inquiryNumber: string, content: string, tokens: string[], orderNumber?: string | null,
    refundAccount?: RefundAccountInput | null) => Promise<unknown>;
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
function FollowUp({ inquiry, actions, onDone, open, setOpen, prompt }: {
  inquiry: InquiryPublic; actions: ThreadActions; onDone: () => void;
  open: boolean; setOpen: (open: boolean) => void; prompt?: string;
}) {
  // 쓰던 추가 문의는 문의마다 임시 저장 (새로 고침해도 남음, 보내면 지워짐)
  const draftKey = `inquai.followUp.${inquiry.inquiry_number}`;
  const [text, setTextState] = useState(() => { try { return sessionStorage.getItem(draftKey) ?? ""; } catch { return ""; } });
  const setText = (v: string) => {
    setTextState(v);
    try { if (v) sessionStorage.setItem(draftKey, v); else sessionStorage.removeItem(draftKey); } catch { /* 저장소 없음 */ }
  };
  const [order, setOrder] = useState("");
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // 환불 계좌: 무통장입금 취소·반품인데 아직 없으면 펼쳐 둠, 아니면 [환불 계좌 입력]으로 펼침 (글과 따로, AI에 안 넘김)
  const [refund, setRefund] = useState<RefundAccountInput>(EMPTY_REFUND);
  const [showRefund, setShowRefund] = useState(!!inquiry.refund_account_needed);

  if (!inquiry.can_follow_up) return <p className="text-xs text-slate-500">이 문의에는 더 이상 추가 문의를 남길 수 없어요. 새 문의로 남겨 주세요.</p>;
  if (!open) return <Button variant="ghost" onClick={() => setOpen(true)}>{text ? "쓰던 추가 문의 이어 쓰기" : "내용 보충 · 추가 문의"}</Button>;
  // 주문번호가 없거나, 적은 번호로 내 주문을 찾지 못했으면 다시 받음
  const needsOrder = !inquiry.order_number || !!inquiry.order_needs_fix;
  const orderNumber = needsOrder ? normalizeOrder(order) : "";
  const refundSend = showRefund ? refundValue(refund) : null;
  const ready = (text.trim().length >= 2 || photos.length > 0 || !!orderNumber || !!(refundSend && refundSend !== "invalid"))
    && refundSend !== "invalid";
  const orderError = needsOrder && orderNumber === null && order.replace(/\s/g, "").length >= 8
    ? "주문번호는 20261103-0042처럼 숫자 8자리-4자리예요." : "";

  async function send() {
    setError("");
    setBusy(true);
    try {
      await actions.followUp(inquiry.inquiry_number, text, photos.map((p) => p.token), orderNumber || null,
        refundSend && refundSend !== "invalid" ? refundSend : null);
      setText("");
      setRefund(EMPTY_REFUND);
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
      {prompt && <p className="text-sm font-semibold text-ink">{prompt}</p>}
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
      {inquiry.refund_account && (
        <p className="text-xs text-muted">환불 계좌 등록됨: {inquiry.refund_account.bank} {inquiry.refund_account.number} · {inquiry.refund_account.holder}
          {" "}(바꾸려면 아래를 체크하고 다시 입력)</p>
      )}
      {/* 문의하기의 '파손·불량' 체크와 같은 모양: 체크하면 열리고, 풀면 닫힘.
          필요한 문의에서만 보임: 무통장입금 취소·반품인데 계좌가 없음 / 이미 보낸 계좌를 바꿀 때 / 취소·반품·환불 이야기를 쓸 때 */}
      {(inquiry.refund_account_needed || !!inquiry.refund_account || showRefund
        || REFUND_WORDS.test(`${inquiry.title} ${inquiry.content} ${text}`)) && (
        <RefundAccountToggle checked={showRefund} onToggle={setShowRefund} value={refund} onChange={setRefund} disabled={busy}
          autoNote={inquiry.refund_account_needed ? "무통장입금 주문이라 환불받을 계좌가 필요해요" : undefined} />
      )}
      {error && <Alert>{error}</Alert>}
      <div className="flex flex-wrap items-center justify-end gap-2">
        {/* 글 2자 이상, 또는 사진·주문번호만 있어도 보낼 수 있음 (서버 fill_follow_up 과 같은 조건) */}
        {!ready && !busy && <span className="mr-auto text-xs text-muted">내용을 2자 이상 적거나 사진·주문번호를 넣어 주세요.</span>}
        <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>취소</Button>
        <Button onClick={send} disabled={busy || !ready || orderNumber === null}>{busy ? <Spinner /> : "보내기"}</Button>
      </div>
    </div>
  );
}

/** 고객에게 보이는 상태: 내부 상태 이름(담당자 처리·자동 처리 등) 대신, 마지막 글이 누구 것인지로.
 *  상담원이 '확인 후 다시 안내'를 표시해 두었으면 답변을 받았어도 '추가 안내 예정' */
function CustomerStatus({ waiting, more, closed }: { waiting: boolean; more: boolean; closed?: boolean }) {
  if (closed) return <span className="whitespace-nowrap rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-semibold text-slate-600">종료됨</span>;
  if (waiting) return <span className="whitespace-nowrap rounded-full bg-primary-soft px-2.5 py-0.5 text-xs font-semibold text-primary">답변 준비 중</span>;
  if (more) return <span className="whitespace-nowrap rounded-full bg-primary-soft px-2.5 py-0.5 text-xs font-semibold text-primary">추가 안내 예정</span>;
  return <span className="whitespace-nowrap rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">답변 완료</span>;
}

export default function InquiryThreads({ items, notice, actions, reload }: {
  items: InquiryPublic[]; notice: string; actions: ThreadActions; reload: () => Promise<void>;
}) {
  const [error, setError] = useState("");
  // 문의마다: 완료 안내(추가 문의 접수·평가 감사), 추가 문의 칸 열림, 👎 뒤 질문
  const [done, setDone] = useState<Record<string, string>>({});
  const [followOpen, setFollowOpen] = useState<Record<string, boolean>>({});
  const [askWhy, setAskWhy] = useState<Record<string, boolean>>({});
  const say = (n: string, text: string) => setDone((d) => ({ ...d, [n]: text }));
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
      if (helpful) {
        say(inquiryNumber, "평가해 주셔서 감사합니다. 더 좋은 답변을 드리는 데 참고할게요.");
        setAskWhy((a) => ({ ...a, [inquiryNumber]: false }));
      } else {
        // 👎: 무엇이 부족했는지 바로 적을 수 있게 추가 문의 칸을 엶 (적으면 담당자가 다시 확인)
        say(inquiryNumber, "");
        setAskWhy((a) => ({ ...a, [inquiryNumber]: true }));
        setFollowOpen((o) => ({ ...o, [inquiryNumber]: true }));
      }
      await reload();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="space-y-3">
      {error && <Alert>{error}</Alert>}
      {items.map((found) => {
        // 내 글(처음 문의 + 추가 문의)과 고객센터 답변을 시간순으로
        const thread = [
          { kind: "me" as const, at: found.created_at, text: found.content, messageId: null as number | null },
          ...found.messages.map((m) => ({ kind: "me" as const, at: m.at, text: m.text, messageId: m.id as number | null })),
          ...found.answers.map((a) => ({ kind: "answer" as const, at: a.answered_at, text: a.text, a })),
        ].sort((x, y) => new Date(x.at).getTime() - new Date(y.at).getTime());
        const last = thread[thread.length - 1];
        // 답변 없이 종료(중복·스팸·철회 등): 기다리는 중이 아니라 '종료됨'과 사유 안내
        const closed = found.status === "완료" && !!found.closed_note;
        const waiting = !closed && last.kind === "me";
        const isOpen = open.has(found.inquiry_number);
        return (
          <section key={found.inquiry_number} className="overflow-hidden rounded-2xl border border-hairline bg-white">
            <button type="button" onClick={() => toggle(found.inquiry_number)} aria-expanded={isOpen}
              className={cx("flex w-full items-start gap-3 px-5 py-4 text-left hover:bg-surface-soft", isOpen && "border-b border-hairline")}>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-base font-semibold text-ink">{found.title}</span>
                  <CustomerStatus waiting={waiting} more={!!found.more_answer_coming} closed={closed} />
                </span>
                <span className="mt-0.5 block text-xs text-muted">
                  {formatDate(found.created_at)} · <span className="font-mono">{found.inquiry_number}</span>
                  {found.order_number && <> · 주문 <span className="font-mono">{found.order_number}</span></>}
                </span>
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
                  {closed && <Note>이 문의는 답변 없이 종료되었어요. {found.closed_note}</Note>}
                  {!waiting && !closed && found.more_answer_coming && <Note>담당자가 확인한 뒤 이어서 안내해 드릴게요.</Note>}
                </div>
                {done[found.inquiry_number] && <div className="mt-3"><Alert kind="success">{done[found.inquiry_number]}</Alert></div>}
                <div className="mt-3">
                  <FollowUp inquiry={found} actions={actions}
                    open={!!followOpen[found.inquiry_number]}
                    setOpen={(o) => {
                      setFollowOpen((f) => ({ ...f, [found.inquiry_number]: o }));
                      if (!o) setAskWhy((a) => ({ ...a, [found.inquiry_number]: false }));
                    }}
                    prompt={askWhy[found.inquiry_number] ? "어떤 점이 부족했나요? 알려 주시면 담당자가 다시 확인해 드릴게요." : undefined}
                    onDone={() => {
                      setAskWhy((a) => ({ ...a, [found.inquiry_number]: false }));
                      say(found.inquiry_number, "추가 문의가 접수되었습니다. 담당자가 확인 후 답변드릴게요.");
                      reload();
                    }} />
                </div>
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
