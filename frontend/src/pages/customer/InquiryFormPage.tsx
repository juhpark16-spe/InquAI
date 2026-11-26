// 고객 문의 폼 (/inquiry): 등록하면 그 자리에서 자동 답변 또는 접수 안내를 보여 줍니다 (동기 방식).
// 쇼핑몰에 로그인한 고객은 이름·이메일·조회 비밀번호를 쓰지 않고, 주문을 목록에서 고릅니다 (/inquiry?order=… 로 미리 선택)
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { useShop } from "../../auth/ShopProvider";
import { Bubble, Note, Thumbs } from "../../components/Chat";
import FaqSuggestions from "../../components/FaqSuggestions";
import { EMPTY_REFUND, REFUND_WORDS, RefundAccountToggle, refundValue } from "../../components/RefundAccountFields";
import InquiryThreads from "../../components/InquiryThreads";
import PhotoPicker, { PhotoSlot, type PickedPhoto } from "../../components/PhotoPicker";
import { Alert, Button, Card, Field, Input, MemberBadge, Select, Spinner, Textarea, cx } from "../../components/ui";
import { customerApi, errorCode, errorMessage, shopApi } from "../../services/api";
import type { InquiryCreated, InquiryPublic, RefundAccountInput, ShopOrder } from "../../services/types";

const EMPTY = { customer_name: "", customer_email: "", order_number: "", title: "", content: "", password: "", password2: "" };
// 주문과 관련된 문의로 보이는 표현 (주문번호 입력 권유용, 판단이 틀려도 입력은 선택이라 영향 없음)
const ORDER_WORDS = /배송|택배|송장|도착|못\s?받|안\s?와|출고|주문|취소|교환|반품|환불|파손|누락|오배송|불량|사이즈/;
// 파손·불량·오배송으로 보이는 표현 → 송장·파손 부위 사진 두 칸 (서버 backend/services/photo_evidence.py 의 DAMAGE_PATTERN 과 같아야 함)
const DAMAGE_WORDS = /파손|깨(져|졌|짐|진)|찢(어|겨|긴|김)|불량|오배송|잘못\s?(왔|온|배송)|다른\s?(상품|제품|물건)이\s?(왔|배송)|흠집|스크래치|찌그러|구멍이|얼룩|변색/;
const SLOTS = [
  { label: "송장" as const, guide: "택배 상자의 송장(운송장 번호)이 보이게 한 장" },
  { label: "파손 부위" as const, guide: "깨짐·찢어짐·불량·잘못 온 상품이 잘 보이게 한 장" },
];
// 쇼핑몰 주문번호: 주문일 8자리-그날 순번 4자리 (서버 backend/schemas/inquiry.py 의 normalize_order_number 와 같은 규칙)
const ORDER_HELP = "주문번호는 20261103-0042처럼 숫자 8자리-4자리예요. 마이페이지 > 주문내역에서 확인해 주세요.";
/** 공백 제거, 12자리 숫자면 8-4 로. 형식이 맞으면 고친 번호, 아니면 null (빈칸은 "") */
function normalizeOrder(raw: string): string | null {
  const v = raw.replace(/\s/g, "");
  if (!v) return "";
  const fixed = /^\d{12}$/.test(v) ? `${v.slice(0, 8)}-${v.slice(8)}` : v;
  return /^\d{8}-\d{4}$/.test(fixed) ? fixed : null;
}
// 쓰던 문의를 임시 저장 (새로 고침·실수로 창을 옮겨도 남음, 탭을 닫으면 지워짐). 비밀번호는 저장하지 않음
const DRAFT_KEY = "inquai.inquiryDraft";
type Draft = Pick<typeof EMPTY, "customer_name" | "customer_email" | "order_number" | "title" | "content">;
function readDraft(): Draft | null {
  try {
    const d = JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? "null");
    return d && (d.title || d.content) ? d : null;
  } catch { return null; }
}
function clearDraft() { try { sessionStorage.removeItem(DRAFT_KEY); } catch { /* 저장소를 못 쓰는 브라우저 */ } }
const newRequestId = () => (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`);
const WAIT_MESSAGES = ["문의 내용을 분석하고 있습니다…", "답변을 작성하고 있습니다…", "조금만 기다려 주세요…"];

export default function InquiryFormPage() {
  const { customer } = useShop();
  const [params] = useSearchParams();
  const [orders, setOrders] = useState<ShopOrder[]>([]);
  const presetOrder = params.get("order") ?? "";
  const [restored] = useState(readDraft);
  const [form, setForm] = useState(() => ({ ...EMPTY, ...restored, ...(presetOrder ? { order_number: presetOrder } : {}) }));
  // 같은 문의를 두 번 등록하지 않게: 응답이 늦어 다시 눌러도 서버가 같은 번호로 처리 (등록에 성공하면 새로 만듦)
  const [requestId, setRequestId] = useState(newRequestId);
  const [showRestored, setShowRestored] = useState(!!restored);
  const [copied, setCopied] = useState(false);
  const [sending, setSending] = useState(false);
  const [waitStep, setWaitStep] = useState(0);
  const [error, setError] = useState("");
  const [result, setResult] = useState<InquiryCreated | null>(null);
  const [lookupEmail, setLookupEmail] = useState("");
  const errorBox = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (error) errorBox.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [error]);
  // AI가 바로 답한 문의: 이 자리에서 👍/👎·추가 문의까지 (문의 조회와 같은 대화 화면).
  // 비회원은 방금 입력한 이메일·비밀번호를 화면 메모리에서만 다시 씀 (주소·저장소에 남기지 않음)
  const [thread, setThread] = useState<InquiryPublic | null>(null);
  async function loadThread() {
    if (!result) return;
    const r = customer ? await shopApi.inquiries() : await customerApi.lookup(lookupEmail, form.password);
    setThread(r.items.find((i) => i.inquiry_number === result.inquiry_number) ?? null);
  }
  useEffect(() => {
    setThread(null);
    if (result?.answer) loadThread().catch(() => setThread(null));   // 못 불러오면 지금처럼 답변만 보여 줌
  }, [result]); // eslint-disable-line react-hooks/exhaustive-deps
  const [sentAt, setSentAt] = useState<string | null>(null);
  const [photos, setPhotos] = useState<PickedPhoto[]>([]);
  // 파손·불량·오배송 문의: 송장·파손 부위 사진 두 칸 (지금 사진이 없으면 '나중에' 체크)
  const [evidence, setEvidence] = useState<Record<string, PickedPhoto | null>>({ "송장": null, "파손 부위": null });
  // '상품이 파손·불량이거나 잘못 왔어요' 체크: null = 내용으로 자동 판단, true/false = 고객이 직접 체크하거나 풂
  const [damageChoice, setDamageChoice] = useState<boolean | null>(null);
  const [photosLater, setPhotosLater] = useState(false);
  const [photoTried, setPhotoTried] = useState(false);
  const [agreed, setAgreed] = useState(false);
  // 환불 계좌 (무통장입금 주문 취소·반품): 회원이 고른 주문이 무통장입금이면 펼침, 비회원은 [무통장입금으로 결제했어요]로 펼침
  const [refund, setRefund] = useState<RefundAccountInput>(EMPTY_REFUND);
  const [refundChoice, setRefundChoice] = useState<boolean | null>(null);   // null = 고른 주문을 보고 자동 (무통장입금이면 체크)

  useEffect(() => {
    if (!sending) return;
    setWaitStep(0);
    const timer = setInterval(() => setWaitStep((s) => Math.min(s + 1, WAIT_MESSAGES.length - 1)), 4000);
    return () => clearInterval(timer);
  }, [sending]);

  useEffect(() => {
    if (result) return;
    const { customer_name, customer_email, order_number, title, content } = form;
    try {
      if (title || content) sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ customer_name, customer_email, order_number, title, content }));
      else sessionStorage.removeItem(DRAFT_KEY);
    } catch { /* 저장소를 못 쓰는 브라우저: 임시 저장 없이 그대로 씀 */ }
  }, [form, result]);

  useEffect(() => {
    if (customer) shopApi.orders().then(setOrders).catch(() => setOrders([]));
  }, [customer]);

  const needsOrder = !form.order_number.trim() && ORDER_WORDS.test(`${form.title} ${form.content}`);
  const orderNumber = customer ? form.order_number : normalizeOrder(form.order_number);
  const bankTransfer = !!customer && orders.find((o) => o.order_number === form.order_number)?.payment_method === "무통장입금";
  const showRefund = refundChoice ?? bankTransfer;
  // 필요한 문의에서만 보임: 회원은 무통장입금 주문을 골랐을 때, 비회원은 제목·내용에 취소·반품·환불이 있을 때 (이미 체크했으면 계속 보임)
  const refundRelevant = customer ? bankTransfer : REFUND_WORDS.test(`${form.title} ${form.content}`);
  const refundSend = showRefund ? refundValue(refund) : null;
  // 다 적기 전(8자리 미만)에는 재촉하지 않음
  const orderError = !customer && orderNumber === null && form.order_number.replace(/\s/g, "").length >= 8 ? ORDER_HELP : "";
  const damageWords = DAMAGE_WORDS.test(`${form.title} ${form.content}`);
  const damageMode = damageChoice ?? damageWords;
  const evidencePhotos = SLOTS.map((s) => evidence[s.label]).filter((p): p is PickedPhoto => !!p);
  const missingSlots = SLOTS.filter((s) => !evidence[s.label]).map((s) => s.label);
  // 파손 체크를 풀면 숨은 칸의 사진은 보내지 않음 (고객이 볼 수 없는 사진이 함께 등록되지 않게)
  const allPhotos = [...(damageMode ? evidencePhotos : []), ...photos];
  const set = (key: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!customer && form.password !== form.password2) {
      setError("비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    if (orderNumber === null) {
      setError(ORDER_HELP);
      return;
    }
    if (refundSend === "invalid") {
      setError("환불 계좌의 은행·예금주·계좌번호를 모두 적어 주세요. (필요 없으면 칸을 비워 두세요)");
      return;
    }
    if (allPhotos.length > 3) {
      setError("사진은 모두 3장까지 올릴 수 있어요. 다른 사진을 빼 주세요.");
      return;
    }
    if (damageMode && !photosLater && missingSlots.length) {
      setPhotoTried(true);
      setError(`파손·불량·오배송 문의는 ${missingSlots.join(" · ")} 사진이 필요해요. 지금 사진이 없으면 '지금은 사진이 없어요'를 체크해 주세요.`);
      return;
    }
    setSending(true);
    try {
      const { password2: _, ...body } = form;
      // 로그인 고객: 이름·이메일은 서버가 계정 정보로 채움, 조회 비밀번호 없음
      const who = customer ? { customer_name: customer.name, customer_email: customer.email, password: null } : {};
      setResult(await customerApi.create({ ...body, ...who, order_number: orderNumber || null,
        privacy_agreed: agreed, attachment_tokens: allPhotos.map((p) => p.token),
        photo_labels: damageMode
          ? Object.fromEntries(SLOTS.flatMap((s) => (evidence[s.label] ? [[evidence[s.label]!.token, s.label]] : []))) : {},
        damage_report: damageChoice, photos_later: damageMode && photosLater, client_request_id: requestId,
        refund_account: refundSend }));
      clearDraft();
      setShowRestored(false);
      setRequestId(newRequestId());
      setLookupEmail(form.customer_email);
      setSentAt(new Date().toISOString());
    } catch (err) {
      if (errorCode(err) === "PHOTO_REQUIRED") {   // 서버가 파손 문의로 판단 → 사진 두 칸을 보여 줌
        setDamageChoice(true);
        setPhotoTried(true);
      }
      // 응답이 늦은 경우: 이미 접수됐을 수 있음. 같은 요청 번호로 다시 보내면 두 번 등록되지 않음
      const timedOut = (err as { code?: string })?.code === "ECONNABORTED";
      setError(timedOut
        ? "응답이 늦어지고 있어요. 문의가 이미 접수됐을 수 있어요. [문의 등록]을 한 번 더 누르면 두 번 등록되지 않고 결과를 보여 드려요."
        : errorMessage(err));
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
            <dd className="flex items-center gap-2">
              <span className="font-mono font-semibold text-slate-900">{result.inquiry_number}</span>
              <button type="button" className="rounded-lg border border-hairline px-2 py-0.5 text-xs text-body hover:bg-surface-soft"
                onClick={() => navigator.clipboard?.writeText(result.inquiry_number).then(() => {
                  setCopied(true); setTimeout(() => setCopied(false), 2000);
                }).catch(() => {})}>{copied ? "복사됨 ✓" : "복사"}</button>
            </dd>
            <dt className="text-slate-500">처리 상태</dt>
            {/* 내부 상태(자동 처리·검토 대기 등) 대신 고객 말로 (문의 조회·내 쇼핑과 같은 표시) */}
            <dd>{result.answer
              ? <span className="rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-semibold text-emerald-700">답변 완료</span>
              : <span className="rounded-full bg-primary-soft px-2.5 py-0.5 text-xs font-semibold text-primary">답변 준비 중</span>}</dd>
          </dl>
          {/* 대화형: 내가 보낸 문의(오른쪽) → AI 답변 또는 접수 안내(왼쪽). 답변이 있으면 평가·추가 문의가 되는 대화 화면으로 */}
          {thread ? (
            <InquiryThreads items={[thread]} notice="" reload={loadThread} actions={customer ? {
              rate: (n, id, helpful) => shopApi.rate(id, n, helpful),
              followUp: (n, text, tokens, order, account) => shopApi.followUp(n, text, tokens, order, account),
            } : {
              rate: (n, id, helpful) => customerApi.rate(id, n, lookupEmail, form.password, helpful),
              followUp: (n, text, tokens, order, account) => customerApi.followUp(lookupEmail, form.password, n, text, tokens, order, account),
            }} />
          ) : (
          <div className="space-y-4 rounded-xl bg-slate-50 p-4">
            <Bubble side="right" tone="customer" name="나" at={sentAt}
              footer={<Thumbs photos={allPhotos.map((p) => ({ url: p.preview, filename: p.name }))} />}>{form.content}</Bubble>
            {result.answer
              ? <Bubble side="left" tone="ai" name="AI 상담원" at={sentAt}>{result.answer}</Bubble>
              : <Note>{result.message}</Note>}
          </div>
          )}
          {result.answer && <p className="mt-3 text-xs text-slate-500">{result.message}</p>}
          {damageMode && photosLater && missingSlots.length > 0 && (
            <p className="mt-3 rounded-lg bg-primary-soft px-3 py-2 text-sm text-ink">
              사진은 {customer ? "내 쇼핑 > 내 문의" : "문의 조회"}의 <b>[내용 보충 · 추가 문의]</b>로 보내 주세요. 송장이 보이는 사진 1장과 파손 부위 사진 1장이 있으면 바로 확인해 드려요.
            </p>
          )}
        </Card>
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => {
            // 주문 화면에서 들어왔으면(?order=) 같은 주문으로 새 문의를 쓰기 쉽게 그대로 둠
            setResult(null); setThread(null); setForm({ ...EMPTY, order_number: presetOrder }); setPhotos([]); setRefund(EMPTY_REFUND); setRefundChoice(null); setAgreed(false);
            setEvidence({ "송장": null, "파손 부위": null }); setDamageChoice(null); setPhotosLater(false); setPhotoTried(false);
          }}>새 문의 작성</Button>
          {/* 이메일은 주소(URL)에 남기지 않고 화면 이동 상태로만 넘김 */}
          <Link to={customer ? "/my" : "/inquiry/lookup"} state={customer ? undefined : { email: lookupEmail }}
            className="inline-flex min-h-11 items-center rounded-xl border border-hairline bg-canvas px-5 py-2.5 text-sm font-semibold text-ink hover:bg-surface-card">
            {customer ? "내 문의 보기" : "문의 조회로 이동"}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 페이지 제목은 다른 화면(내 쇼핑·FAQ)과 같은 크기로 카드 밖에 */}
      <div>
        <h1 className="page-title flex flex-wrap items-center gap-2">1:1 문의하기 <MemberBadge name={customer?.name} /></h1>
        <p className="mt-1 text-sm text-muted">자주 묻는 질문은 바로 답변드리고, 담당자 확인이 필요한 문의는 영업일 기준 1일 이내(평일 10:00~17:00)에 답변드려요.</p>
      </div>
    <Card>
      <form onSubmit={submit} className="space-y-4">
        {showRestored && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-primary-soft px-3 py-2 text-sm text-ink">
            <span>쓰던 문의를 불러왔어요. (사진·비밀번호는 다시 넣어 주세요)</span>
            <button type="button" className="text-xs font-semibold text-primary underline" onClick={() => {
              clearDraft(); setShowRestored(false); setForm({ ...EMPTY, order_number: presetOrder });
            }}>지우고 새로 쓰기</button>
          </div>
        )}
        {/* 로그인 상태는 제목 옆 배지와 오른쪽 위 메뉴(로그인 · 내 쇼핑)에서 보여 줌 */}
        {!customer && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="이름">
            <Input required maxLength={50} value={form.customer_name} onChange={set("customer_name")} disabled={sending} />
          </Field>
          <Field label="이메일" hint="주문할 때 쓴 이메일로 적어 주세요. 그래야 주문 내용을 확인해 드릴 수 있어요. (문의 조회에도 씁니다)">
            <Input required type="email" maxLength={255} value={form.customer_email} onChange={set("customer_email")} disabled={sending} />
          </Field>
          <Field label="조회 비밀번호" hint="6자 이상 · 이메일과 함께 문의 조회에 써요. 찾을 수 없으니 기억해 두세요. 이전 문의와 같은 비밀번호를 쓰면 한 번에 조회돼요.">
            <Input required type="password" minLength={6} maxLength={64} autoComplete="new-password"
              value={form.password} onChange={set("password")} disabled={sending} />
          </Field>
          {/* 입력하는 동안 바로 알려 줌 (등록을 눌러야 아래에서 알게 되지 않게) */}
          <Field label="비밀번호 확인" error={form.password2 && form.password2 !== form.password ? "위 비밀번호와 달라요." : undefined}>
            <Input required type="password" minLength={6} maxLength={64} autoComplete="new-password"
              value={form.password2} onChange={set("password2")} disabled={sending} />
          </Field>
        </div>
        )}

        <Field label="제목">
          <Input required maxLength={200} value={form.title} onChange={set("title")} disabled={sending} />
        </Field>
        <Field label="문의 내용" hint={`${form.content.length} / 2,000자 (5자 이상)`}>
          <Textarea required minLength={5} maxLength={2000} value={form.content} onChange={set("content")} disabled={sending} />
        </Field>
        {/* 주문번호는 선택. 주문 관련 내용(배송·취소·교환·반품 등)을 쓰면 칸을 강조해 입력을 권유 */}
        {customer ? (
          <Field label="주문 (선택)" hint={needsOrder ? "주문 관련 문의 같아요. 해당 주문을 고르시면 바로 확인해 더 빨리 처리해 드려요." : "주문과 관련된 문의라면 골라 주세요."}>
            <Select className={cx("w-full", needsOrder && "border-amber-400 bg-amber-50/50 ring-2 ring-amber-100")}
              value={form.order_number} onChange={set("order_number")} disabled={sending}>
              <option value="">주문과 관계없는 문의</option>
              {orders.map((o) => (
                <option key={o.order_number} value={o.order_number}>{o.product_name} · {o.order_number} ({o.order_status})</option>
              ))}
            </Select>
          </Field>
        ) : (
        <Field label="주문번호 (선택)" error={orderError}
          hint={needsOrder ? "주문 관련 문의 같아요. 주문번호를 적어 주시면 더 빨리 확인해 드려요. (예: 20261103-0042)"
            : "주문 관련 문의라면 적어 주세요. 마이페이지 > 주문내역에 있어요. (예: 20261103-0042)"}>
          <Input maxLength={30} value={form.order_number} onChange={set("order_number")} disabled={sending}
            inputMode="numeric" placeholder="20261103-0042" aria-invalid={!!orderError}
            onBlur={() => { if (orderNumber) setForm((f) => ({ ...f, order_number: orderNumber })); }}
            className={cx(orderError ? "border-rose-400 ring-2 ring-rose-100" : needsOrder && "border-amber-400 bg-amber-50/50 ring-2 ring-amber-100")} />
        </Field>
        )}
        {/* 무통장입금 주문의 취소·반품: 환불 계좌를 글과 따로 받음 (AI에 넘기지 않음) */}
        {(refundRelevant || showRefund) && (
          <RefundAccountToggle checked={showRefund} onToggle={setRefundChoice} value={refund} onChange={setRefund} disabled={sending}
            autoNote={bankTransfer && refundChoice === null ? "고르신 주문이 무통장입금이라 체크했어요" : undefined} />
        )}
        {/* 파손·불량·오배송: 체크 하나로 (내용에 그런 표현이 보이면 자동으로 체크, 고객이 풀 수 있음) → 송장·파손 부위 사진 두 칸 */}
        <div className="space-y-2">
          <label className={cx("flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm",
            damageMode ? "border-primary/30 bg-primary-soft/50" : "border-hairline bg-white")}>
            <input type="checkbox" className="mt-0.5" checked={damageMode} disabled={sending}
              onChange={(e) => { setDamageChoice(e.target.checked); if (!e.target.checked) setPhotoTried(false); }} />
            <span>
              <span className="font-semibold text-ink">상품이 파손·불량이거나 잘못 왔어요</span>
              {damageWords && damageChoice === null && <span className="ml-1 text-xs text-primary">· 내용을 보니 그런 문의 같아 체크했어요</span>}
              <span className="block text-xs text-muted">체크하면 송장 사진과 파손 부위 사진을 올리는 칸이 열려요. 사진이 있으면 다시 여쭙지 않고 바로 확인해 드려요.</span>
            </span>
          </label>
          {damageMode ? (
            <div className="space-y-2 rounded-xl border border-primary/20 bg-primary-soft/30 p-3">
              <p className="text-xs text-muted">두 장 모두 올려야 등록돼요.</p>
              {SLOTS.map((s) => (
                <PhotoSlot key={s.label} label={s.label} guide={s.guide} value={evidence[s.label]} disabled={sending || photosLater}
                  missing={photoTried && !photosLater && !evidence[s.label]}
                  onChange={(p) => setEvidence((prev) => ({ ...prev, [s.label]: p }))} />
              ))}
              <div className="space-y-1">
                <span className="text-xs text-muted">다른 사진 (선택, {Math.max(0, 3 - evidencePhotos.length)}장까지)</span>
                <PhotoPicker value={photos} onChange={setPhotos} disabled={sending} max={3 - evidencePhotos.length} />
              </div>
              <label className="flex items-start gap-2 text-sm text-ink">
                <input type="checkbox" className="mt-0.5" checked={photosLater} disabled={sending} onChange={(e) => setPhotosLater(e.target.checked)} />
                <span>지금은 사진이 없어요 <span className="text-xs text-muted">(등록 후 [내용 보충 · 추가 문의]로 보내 주세요. 사진이 와야 확인할 수 있어요)</span></span>
              </label>
            </div>
          ) : (
            <div className="space-y-1">
              <span className="text-sm font-medium text-slate-700">사진 첨부 (선택)</span>
              <PhotoPicker value={photos} onChange={setPhotos} disabled={sending} />
              <span className="block text-xs text-muted">3장, 한 장 5MB까지</span>
            </div>
          )}
        </div>
        {!sending && <FaqSuggestions text={`${form.title} ${form.content}`} />}

        {/* 개인정보 수집·이용 동의 (비회원 문의라 이름·이메일을 받으므로 필수). 안내 내용은 '내용 보기'로 펼침 */}
        <div className="rounded-xl border border-hairline bg-surface-soft/60 px-4 py-3 text-sm">
          <label className="flex items-center gap-2 font-medium text-ink">
            <input type="checkbox" required checked={agreed} onChange={(e) => setAgreed(e.target.checked)} disabled={sending} />
            개인정보 수집·이용에 동의합니다 (필수)
          </label>
          <details className="mt-1.5 pl-6 text-xs leading-relaxed text-muted">
            <summary className="cursor-pointer hover:text-primary">내용 보기</summary>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-4">
              <li>수집 항목: 이름, 이메일, 주문번호(선택), 문의 내용, 첨부 사진(선택)</li>
              <li>이용 목적: 문의 확인·답변, 주문 확인, 답변 알림</li>
              <li>보관 기간: 문의 처리 후 3년 (전자상거래법의 소비자 불만·분쟁 처리 기록 보존 기간)</li>
              <li>문의 내용은 빠른 답변을 위해 AI 분석에 쓰이며, 외부 AI 서비스(OpenAI)에서 처리될 수 있습니다.</li>
              <li>AI 답변 품질 점검을 위해 처리 기록이 외부 서비스(LangSmith)에 보관될 수 있으며, 이때 이메일·전화번호·주문번호 등은 가려서 보냅니다.</li>
              <li>동의하지 않으실 수 있으나, 동의하지 않으면 1:1 문의를 등록할 수 없습니다.</li>
            </ul>
          </details>
        </div>
        {/* 오류는 등록 버튼 바로 위: 휴대폰에서 안 보일 수 있으니 생기면 이 자리로 화면을 옮김 */}
        {error && <div ref={errorBox} className="scroll-mt-28"><Alert>{error}</Alert></div>}
        <Button type="submit" disabled={sending} className="w-full py-2.5">
          {sending ? <span className="inline-flex items-center gap-2"><Spinner />{WAIT_MESSAGES[waitStep]}</span> : "문의 등록"}
        </Button>
        {sending ? <p className="text-center text-xs text-slate-500">자동 답변을 작성하는 경우 10초 정도 걸릴 수 있습니다.</p>
          : null}
      </form>
    </Card>
    </div>
  );
}
