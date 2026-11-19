// 문의와 답변 + 답변 작성 영역 (문의 상세)
// - 문의와 답변: 고객(왼쪽: 처음 문의·추가 문의·사진) / AI·상담원 답변(오른쪽, 고객 평가 표시) / 내부 메모(노란색, 고객에게 안 보임)
//         사이사이 티켓 처리·AI 오류 안내 (배정·상태 변경·알림은 '전체 처리 이력'에서)
// - 입력: [답변] 탭 = 초안 저장·발송 (AI 초안이 있으면 채워 둠, [AI 초안 만들기], 참고 FAQ 넣기) / [내부 메모] 탭 = 상담원끼리 메모
// - AI 초안의 [확인 필요: …] 표시와 확인할 것 목록을 보여 주고, 표시가 남은 채로 보내려 하면 한 번 더 물음
import { useEffect, useRef, useState } from "react";

import { customerApi, errorMessage, inquiryApi, responseApi } from "../services/api";
import type { FaqPublic, InquiryDetail } from "../services/types";
import { Bubble, Note } from "./Chat";
import { Alert, Button, Spinner, Textarea, cx, formatDate } from "./ui";

const MAX = 4000;
const CHECK_MARK = "[확인 필요";

function Photos({ data, messageId }: { data: InquiryDetail; messageId: number | null }) {
  const list = data.attachments.filter((a) => a.message_id === messageId);
  if (!list.length) return null;
  return (
    <span className="mt-1 flex flex-wrap gap-1.5">
      {list.map((a) => {
        const url = inquiryApi.attachmentUrl(data.id, a.id);
        return (
          <a key={a.id} href={url} target="_blank" rel="noreferrer" title={`${a.filename} (${Math.round(a.size / 1024)}KB) · 크게 보기`}>
            <img src={url} alt={a.filename} className="h-20 w-20 rounded-lg border border-slate-200 object-cover hover:opacity-90" />
          </a>
        );
      })}
    </span>
  );
}

function RatingBadge({ rating }: { rating: number | null }) {
  if (rating === null) return <span className="text-slate-500">고객 평가 전</span>;
  return rating > 0 ? <span className="text-emerald-700">고객 평가 👍 도움됨</span> : <span className="text-rose-700">고객 평가 👎 도움 안 됨</span>;
}

// 자주 쓰는 문구 (FAQ·쇼핑몰 정책과 같은 내용만, docs/shop_policy.md). 커서 자리에 넣음
const TEMPLATES: [string, string][] = [
  ["첫인사", "안녕하세요, 고객님. InquAI 쇼핑 고객센터입니다."],
  ["사과", "불편을 드려 죄송합니다."],
  ["취소 완료", "요청하신 주문 취소가 완료되었습니다. 결제 취소는 신용·체크카드 3~5영업일, 계좌이체·간편결제는 1~3영업일 안에 반영됩니다."],
  ["출고 후 취소 불가", "이미 출고된 주문은 취소할 수 없어, 상품을 받으신 뒤 마이페이지 > 주문내역에서 반품을 신청해 주세요."],
  ["회수 안내", "지정 택배사가 1~3영업일 안에 방문해 상품을 회수합니다. 받으신 상태 그대로 포장해 두어 주세요."],
  ["환불 일정", "반품 상품이 물류센터에 도착해 검수가 끝나면 3영업일 이내에 환불됩니다. 카드 결제는 카드사 사정에 따라 3~5영업일이 더 걸릴 수 있습니다."],
  ["파손·오배송", "파손·누락·오배송은 배송비를 저희가 부담합니다. 받으신 상품 사진을 함께 보내 주시면 더 빨리 확인해 드리겠습니다."],
  ["마무리", "추가로 궁금하신 점은 언제든 문의해 주세요. 감사합니다."],
];

// AI 초안 다시 만들기에 붙일 요청 (상담원이 직접 적어도 됨, 200자)
const DRAFT_ASKS = ["더 짧게", "사과를 먼저", "더 정중하게", "회수·환불 일정 안내 추가"];

export default function AnswerComposer({ data, refFaqCodes, onChanged }: {
  data: InquiryDetail;
  refFaqCodes: string[];
  onChanged: () => void;
}) {
  const sent = data.responses.filter((r) => r.status === "발송");
  const draft = data.responses.find((r) => r.status === "초안");
  const [mode, setMode] = useState<"answer" | "memo">("answer");
  const [text, setText] = useState(draft ? draft.final_text ?? draft.draft_text : "");
  const [memo, setMemo] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "send" | "memo" | "draft">("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [faqs, setFaqs] = useState<Record<string, FaqPublic>>({});
  const [ask, setAsk] = useState("");
  const [tools, setTools] = useState(false); // 문구·주문 정보·초안 요청 버튼은 필요할 때만 펼침
  const box = useRef<HTMLTextAreaElement>(null);

  // 다른 문의로 이동하거나 저장 후 다시 불러오면 입력칸을 최신 초안으로 맞춤
  useEffect(() => {
    setText(draft ? draft.final_text ?? draft.draft_text : "");
  }, [draft?.id, draft?.final_text, draft?.draft_text]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (refFaqCodes.length === 0) return;
    customerApi.faqs().then((list) => setFaqs(Object.fromEntries(list.map((f) => [f.code, f])))).catch(() => setFaqs({}));
  }, [refFaqCodes.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = text.trim() !== (draft ? (draft.final_text ?? draft.draft_text) : "").trim();

  async function run(kind: "save" | "send" | "memo" | "draft", action: () => Promise<unknown>, ok: string) {
    setError("");
    setNotice("");
    setBusy(kind);
    try {
      await action();
      setNotice(ok);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy("");
    }
  }

  const save = (send: boolean) => {
    if (send && text.includes(CHECK_MARK)
      && !window.confirm("답변에 [확인 필요] 표시가 남아 있습니다. 확인한 내용으로 고치지 않고 그대로 보낼까요?")) return;
    return run(send ? "send" : "save", async () => {
    if (draft) await (send ? responseApi.approve(draft.id, text) : responseApi.update(draft.id, text));
    else await responseApi.create(data.id, text, send);
    if (send) setText(""); // 보낸 뒤에는 입력칸을 비워 추가 답변용으로
  }, send ? "답변을 보냈습니다. 고객 조회 화면에 보이고 이메일 알림이 기록되었으며, 문의는 완료로 바뀌었습니다." : "초안을 저장했습니다.");
  };

  // AI 초안 만들기: 상담원이 쓰던 글이 있으면 바꿀지 먼저 물음
  const aiDraft = () => {
    const edited = !!draft && (draft.generated_by !== "llm" || (draft.final_text !== null && draft.final_text !== draft.draft_text));
    const replace = edited || (dirty && !!text.trim());
    if (replace && !window.confirm("작성 중인 답변이 AI 초안으로 바뀝니다. 계속할까요?")) return;
    return run("draft", async () => { await responseApi.draft(data.id, replace, ask); setAsk(""); },
      ask.trim() ? `요청("${ask.trim()}")을 반영해 AI 초안을 다시 만들었습니다. 확인한 뒤 보내 주세요.`
        : "AI 초안을 만들었습니다. [확인 필요] 표시와 아래 확인할 것을 살펴본 뒤 고쳐서 보내 주세요.");
  };
  const checks = draft?.generated_by === "llm" ? draft.check_points ?? [] : [];
  const marks = text.split(CHECK_MARK).length - 1;

  const saveMemo = () => run("memo", async () => { await inquiryApi.addNote(data.id, memo); setMemo(""); }, "내부 메모를 남겼습니다.");

  // 문의와 답변: 고객 글·보낸 답변·내부 메모·티켓 처리를 시간순으로.
  // 배정·상태 변경·알림 기록·AI 판단 같은 시스템 기록은 '전체 처리 이력'에서만 봄 (AI 오류만 여기에도 표시)
  type Item =
    | { type: "customer"; at: string; text: string; messageId: number | null; followUp: boolean }
    | { type: "note"; at: string; text: string; warn: boolean }
    | { type: "memo"; at: string; text: string; author: string }
    | { type: "sent"; at: string; r: (typeof sent)[number]; who: string };
  const sentEvents = data.history.filter((e) => e.kind === "sent");
  const thread: Item[] = [
    { type: "customer" as const, at: data.created_at, text: data.content, messageId: null, followUp: false },
    ...data.messages.map((m) => ({ type: "customer" as const, at: m.created_at, text: m.text, messageId: m.id, followUp: true })),
    ...data.history.filter((e) => e.kind === "ticket" || (e.kind === "ai" && e.text.includes("오류"))).map((e) => ({
      type: "note" as const, at: e.at, warn: e.kind === "ai", text: `${e.actor} · ${e.text}`,
    })),
    ...data.notes.map((n) => ({ type: "memo" as const, at: n.created_at, text: n.text, author: n.author })),
    ...sent.map((r, i) => ({ type: "sent" as const, at: r.approved_at ?? r.created_at, r, who: sentEvents[i]?.actor ?? "상담원" })),
  ].sort((x, y) => new Date(x.at).getTime() - new Date(y.at).getTime());

  /** 커서 자리(선택한 글이 있으면 그 자리)에 넣고, 넣은 글 뒤로 커서를 옮김 */
  function insertAt(raw: string, sentence = false) {
    const el = box.current;
    const start = el?.selectionStart ?? text.length;
    const end = el?.selectionEnd ?? text.length;
    // 문장 문구는 앞뒤 글과 붙지 않게 띄어 줌 ("…입니다.먼저" → "…입니다. 먼저")
    const before = text.slice(0, start), after = text.slice(end);
    const piece = sentence
      ? `${before && !/\s$/.test(before) ? " " : ""}${raw}${after && !/^\s/.test(after) ? " " : ""}` : raw;
    const next = before + piece + after;
    setText(next.slice(0, MAX));
    requestAnimationFrame(() => {
      el?.focus();
      el?.setSelectionRange(start + piece.length, start + piece.length);
    });
  }

  // 본인 확인된 주문의 정보 (주문번호와 문의 이메일이 맞을 때만)
  const o = data.order?.found && data.order.email_match !== false ? data.order : null;
  const orderChips: [string, string][] = o ? ([
    ["주문번호", o.order_number], ["상품명", o.product_name ?? ""], ["주문 상태", o.order_status ?? ""],
    ["송장번호", o.tracking_number ?? ""],
  ] as [string, string][]).filter(([, v]) => v) : [];

  function insertFaq(code: string) {
    const answer = faqs[code]?.answer;
    if (answer) setText((t) => (t.trim() ? `${t.trim()}\n\n${answer}` : answer));
  }

  const tab = (m: "answer" | "memo", label: string) => (
    <button type="button" onClick={() => setMode(m)}
      className={cx("rounded-md px-3 py-1 text-base", mode === m ? (m === "memo" ? "bg-amber-100 font-medium text-amber-900" : "bg-indigo-50 font-medium text-indigo-700") : "text-slate-600 hover:text-slate-800")}>
      {label}
    </button>
  );

  return (
    <div className="space-y-4">
      {/* 대화: 고객(왼쪽) · AI와 상담원(오른쪽) · 내부 메모(노랑) · 사이사이 처리 안내 */}
      <div className="space-y-4 rounded-xl bg-slate-50 p-4">
        {thread.map((item, i) => {
          if (item.type === "note") return <Note key={i} tone={item.warn ? "warn" : "plain"}>{item.text} · {formatDate(item.at)}</Note>;
          if (item.type === "customer") {
            return (
              <Bubble key={i} side="left" tone="customer" at={item.at}
                name={`고객 ${data.customer.name}${item.followUp ? " · 추가 문의" : ""}`}
                footer={<Photos data={data} messageId={item.messageId} />}>
                {item.text}
              </Bubble>
            );
          }
          if (item.type === "memo") {
            return <Bubble key={i} side="right" tone="memo" name={`내부 메모 · ${item.author} (고객에게 안 보임)`} at={item.at}>{item.text}</Bubble>;
          }
          return (
            <Bubble key={i} side="right" tone={item.r.approved_by === null ? "ai" : "agent"} at={item.at}
              name={item.r.approved_by === null ? "AI 자동 답변" : `${item.who}${item.r.generated_by === "llm" ? (item.r.is_edited ? " · AI 초안 수정" : " · AI 초안 그대로") : ""}`}
              footer={
                <span className="flex flex-col items-end gap-0.5">
                  <RatingBadge rating={item.r.rating} />
                  {item.r.used_faq_ids.length > 0 && <span>근거: {item.r.used_faq_ids.map((c) => `${c} ${data.faq_titles[c] ?? ""}`).join(" · ")}</span>}
                </span>
              }>
              {item.r.final_text ?? item.r.draft_text}
            </Bubble>
          );
        })}
        {sent.length === 0 && <Note>아직 고객에게 보낸 답변이 없습니다</Note>}
      </div>

      <div className={cx("space-y-2 rounded-lg border p-3",
        mode === "memo" ? "border-amber-300 bg-amber-50/50" : draft?.generated_by === "llm" ? "border-amber-200 bg-amber-50/40" : "border-slate-200")}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex gap-1">
            {tab("answer", draft ? (draft.generated_by === "llm" ? "AI 답변 초안" : "작성 중인 초안") : sent.length ? "추가 답변" : "답변 작성")}
            {tab("memo", "내부 메모")}
          </div>
          {mode === "answer" && (
            <button type="button" onClick={aiDraft} disabled={!!busy}
              title="FAQ·주문 정보·대화를 근거로 AI가 초안을 씁니다. 모르는 내용은 [확인 필요]로 남깁니다."
              className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-base font-medium text-indigo-700 hover:bg-indigo-100 disabled:opacity-60">
              {busy === "draft" ? <><Spinner /> AI가 초안을 쓰는 중… (10초 안팎)</> : <>✨ {draft?.generated_by === "llm" ? "AI 초안 다시 만들기" : "AI 초안 만들기"}</>}
            </button>
          )}
        </div>

        {mode === "memo" ? (
          <>
            <Textarea value={memo} maxLength={2000} onChange={(e) => setMemo(e.target.value)} className="min-h-24 bg-white"
              placeholder="상담원끼리 공유할 내용 (예: 택배사 확인 중, 내일 오전 재연락). 고객에게는 보이지 않습니다." disabled={!!busy} />
            <div className="flex justify-end">
              <Button disabled={!!busy || !memo.trim()} onClick={saveMemo}>{busy === "memo" ? <Spinner /> : "메모 남기기"}</Button>
            </div>
          </>
        ) : (
          <>
            {refFaqCodes.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 text-sm">
                <span className="text-slate-600">참고 FAQ 넣기:</span>
                {refFaqCodes.map((code) => (
                  <button key={code} type="button" onClick={() => insertFaq(code)} disabled={!faqs[code]}
                    title={faqs[code]?.answer} className="rounded-full border border-slate-300 bg-white px-2 py-0.5 text-slate-700 hover:border-indigo-400 hover:text-indigo-700 disabled:opacity-50">
                    + {code} {data.faq_titles[code] ?? ""}
                  </button>
                ))}
              </div>
            )}
            {checks.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                <p className="mb-1 font-semibold">발송 전에 확인할 것 (AI가 근거로 알 수 없던 내용)</p>
                <ul className="list-disc space-y-0.5 pl-4">{checks.map((c) => <li key={c}>{c}</li>)}</ul>
              </div>
            )}
            {draft?.generated_by === "llm" && checks.length === 0 && draft.grounded === false && (
              <p className="text-sm text-amber-700">FAQ만으로는 답이 부족해 AI가 초안으로 둔 답변입니다. 내용을 확인해 주세요.</p>
            )}
            <button type="button" onClick={() => setTools(!tools)} aria-expanded={tools}
              className="text-sm font-medium text-slate-600 hover:text-primary">
              {tools ? "▾" : "▸"} 문구·주문 정보{draft?.generated_by === "llm" ? "·초안 요청" : ""} 넣기
              {!tools && ask.trim() && <span className="ml-1 text-indigo-700">(초안 요청: {ask.trim()})</span>}
            </button>
            {tools && (
              <div className="space-y-2 rounded-lg bg-slate-50 p-2.5">
                <div className="flex flex-wrap items-center gap-1.5 text-sm">
                  <span className="text-slate-600">문구 넣기:</span>
                  {TEMPLATES.map(([label, piece]) => (
                    <button key={label} type="button" onClick={() => insertAt(piece, true)} title={piece} disabled={!!busy}
                      className="rounded-full border border-slate-300 bg-white px-2 py-0.5 text-slate-700 hover:border-indigo-400 hover:text-indigo-700">
                      {label}
                    </button>
                  ))}
                </div>
                {orderChips.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 text-sm">
                    <span className="text-slate-600">주문 정보 넣기:</span>
                    {orderChips.map(([label, value]) => (
                      <button key={label} type="button" onClick={() => insertAt(value)} title={value} disabled={!!busy}
                        className="rounded-full border border-emerald-300 bg-emerald-50 px-2 py-0.5 text-emerald-800 hover:border-emerald-500">
                        {label} <span className="font-mono">{value.length > 14 ? `${value.slice(0, 14)}…` : value}</span>
                      </button>
                    ))}
                  </div>
                )}
                {draft?.generated_by === "llm" && (
                  <div className="flex flex-wrap items-center gap-1.5 text-sm">
                    <span className="text-slate-600">초안 요청:</span>
                    {DRAFT_ASKS.map((a) => (
                      <button key={a} type="button" onClick={() => setAsk(a)} disabled={!!busy}
                        className={cx("rounded-full border px-2 py-0.5", ask === a ? "border-indigo-500 bg-indigo-50 text-indigo-700" : "border-slate-300 bg-white text-slate-700 hover:border-indigo-400")}>
                        {a}
                      </button>
                    ))}
                    <input value={ask} onChange={(e) => setAsk(e.target.value)} maxLength={200} placeholder="직접 적기 (선택)" disabled={!!busy}
                      className="min-w-32 flex-1 rounded-full border border-slate-300 bg-white px-3 py-0.5 outline-none focus:border-indigo-400" />
                    {ask.trim() && <span className="text-indigo-700">→ 위의 [✨ AI 초안 다시 만들기]를 누르면 반영됩니다</span>}
                  </div>
                )}
              </div>
            )}
            <Textarea ref={box} value={text} maxLength={MAX} onChange={(e) => setText(e.target.value)} className="min-h-40 text-base leading-relaxed"
              onKeyDown={(e) => {
                // 단축키: Ctrl(⌘)+Enter 발송, Ctrl(⌘)+S 초안 저장
                if (!(e.ctrlKey || e.metaKey) || busy) return;
                if (e.key === "Enter" && text.trim()) { e.preventDefault(); save(true); }
                if (e.key.toLowerCase() === "s") { e.preventDefault(); if (text.trim() && (!draft || dirty)) save(false); }
              }}
              placeholder="고객에게 보낼 답변을 입력하세요. 오른쪽 주문 정보와 참고 FAQ를 확인해 주세요." disabled={!!busy} />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm text-slate-500">
                {marks > 0 && <b className="mr-1 font-semibold text-amber-700">[확인 필요] {marks}곳 남음 ·</b>}
                {text.length.toLocaleString()} / {MAX.toLocaleString()}자
              </span>
              <div className="flex gap-2">
                <Button variant="ghost" disabled={!!busy || !text.trim() || (!!draft && !dirty)} onClick={() => save(false)}>
                  {busy === "save" ? <Spinner /> : "초안 저장"}
                </Button>
                <Button disabled={!!busy || !text.trim()} onClick={() => save(true)}
                  title="고객 조회 화면에 보이고 이메일 알림이 기록되며 문의가 완료됩니다 (단축키 Ctrl+Enter · 초안 저장 Ctrl+S · 이전·다음 문의 Alt+←/→)">
                  {busy === "send" ? <Spinner /> : "발송"}
                </Button>
              </div>
            </div>
          </>
        )}
        {error && <Alert>{error}</Alert>}
        {notice && <Alert kind="success">{notice}</Alert>}
      </div>
    </div>
  );
}
