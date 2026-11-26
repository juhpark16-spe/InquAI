// 바로 처리 (배송지·옵션 변경, 부분 취소, 중복 승인 취소, 반품 회수, 보상): 확인창 → 처리 → 안내
import { useState } from "react";
import { confirmDialog } from "../../../components/ConfirmDialog";
import { stockText, won } from "../../../components/OrderParts";
import { Alert, Button, Input, Select, Spinner, cx } from "../../../components/ui";
import { errorMessage, inquiryApi, type QuickAction } from "../../../services/api";
import type { OrderCard } from "../../../services/types";

export const RETURN_FEE = { "단순 변심": "왕복 배송비 6,000원은 환불 금액에서 차감", "불량·오배송": "배송비는 쇼핑몰 부담" } as const;
export const COUPON_CHOICES = [
  { name: "사과 쿠폰 3,000원", note: "3,000원 할인 · 2만원 이상", adminOnly: false },
  { name: "무료배송 쿠폰", note: "배송비 무료", adminOnly: false },
  { name: "사과 쿠폰 5,000원", note: "5,000원 할인 · 3만원 이상 · 관리자만", adminOnly: true },
];

// 바로 처리 확인창: 제목·확인 버튼 이름, 되돌리기 어려운 처리는 빨간 버튼
export const ACTION_CONFIRM: Record<QuickAction, { title: string; label: string; danger?: boolean }> = {
  address: { title: "배송지 변경", label: "배송지 변경" },
  option: { title: "옵션 변경", label: "옵션 변경" },
  partial_cancel: { title: "부분 취소", label: "취소하기", danger: true },
  duplicate_cancel: { title: "중복 승인 취소", label: "승인 취소", danger: true },
  points: { title: "보상 적립금 지급", label: "지급" },
  coupon: { title: "사과 쿠폰 발급", label: "발급" },
  return: { title: "반품 회수 접수", label: "접수" },
  exchange_fee: { title: "교환 배송비 받기", label: "받기" },
};

/** 교환 배송비 상태 한 줄 (주문 정보의 바로 처리·교환 요청 카드가 함께 씀) */
export function exchangeFeeText(o: OrderCard): string | null {
  const f = o.exchange_fee;
  if (!f) return null;
  return f.status === "요청" ? `교환 배송비 ${won(f.amount)}: 고객 결제 대기 (결제 요청함)` : `교환 배송비 ${won(f.amount)} 받음 (${f.method})`;
}

/** 바로 처리 공통: 버튼을 누르면 아래에 작은 입력칸이 열리고 [실행] → 서버가 조건을 다시 확인해 처리 */
export function useQuickAction(inquiryId: number, onDone: (msg: string) => void) {
  const [open, setOpen] = useState<QuickAction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function exec(action: QuickAction, body: Record<string, string | number> = {}, confirmText?: string) {
    const c = ACTION_CONFIRM[action];
    if (confirmText && !(await confirmDialog({ title: c.title, message: confirmText, confirmLabel: c.label, tone: c.danger ? "danger" : "primary" }))) return;
    setError("");
    setBusy(true);
    try {
      const r = await inquiryApi.action(inquiryId, action, body);
      setOpen(null);
      onDone(`${r.message} · [AI 초안 다시 만들기]를 누르면 처리 결과가 답변에 반영돼요.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  const toggle = (a: QuickAction) => { setError(""); setOpen(open === a ? null : a); };
  return { open, busy, error, exec, toggle };
}

export function ActionButton({ label, active, tone = "plain", onClick }: { label: string; active: boolean; tone?: "plain" | "danger"; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-expanded={active}
      className={cx("rounded-lg border px-2.5 py-1 text-sm font-medium transition",
        active ? "border-primary bg-primary-soft text-primary"
          : tone === "danger" ? "border-rose-300 bg-rose-50 text-rose-700 hover:border-rose-400" : "border-hairline bg-white text-body hover:border-primary hover:text-primary")}>
      {label}
    </button>
  );
}

/** 바로 처리 한 가지의 입력칸 + 실행 버튼. 주문 정보의 [바로 처리]와 요청 카드(반품 회수 접수·부분 취소·옵션 변경)가 함께 씀 */
export function ActionForm({ action, o, q }: { action: QuickAction; o: OrderCard; q: ReturnType<typeof useQuickAction> }) {
  const qty = o.quantity ?? 1;
  const choices = o.option_choices ?? [];
  const [address, setAddress] = useState(o.shipping_address ?? "");
  const [option, setOption] = useState("");
  const [count, setCount] = useState(1);
  const [reason, setReason] = useState<keyof typeof RETURN_FEE>(o.returnable ? "단순 변심" : "불량·오배송");
  return (
    <div className="mt-2.5 space-y-2 rounded-lg bg-white p-2.5 text-sm">
      {action === "duplicate_cancel" && (
        <>
          <p>같은 금액으로 두 번 승인된 것 중 <b>뒤 승인 1건</b>을 취소합니다. 카드사에 따라 3~5영업일 안에 반영돼요.</p>
          <Button className="min-h-9 px-4 py-1" disabled={q.busy} onClick={() => q.exec("duplicate_cancel", {}, "중복 승인 1건을 취소할까요?")}>{q.busy ? <Spinner /> : "중복 승인 취소"}</Button>
        </>
      )}
      {action === "address" && (
        <>
          <p className="text-xs text-muted">지금 배송지: {o.shipping_address ?? "정보 없음"}</p>
          <Input value={address} onChange={(e) => setAddress(e.target.value)} maxLength={200} aria-label="새 배송지" />
          <Button className="min-h-9 px-4 py-1" disabled={q.busy || address.trim().length < 5 || address.trim() === o.shipping_address}
            onClick={() => q.exec("address", { address: address.trim() }, `배송지를 '${address.trim()}'(으)로 바꿀까요?`)}>{q.busy ? <Spinner /> : "배송지 변경"}</Button>
        </>
      )}
      {action === "option" && (
        <>
          <Select value={option} onChange={(e) => setOption(e.target.value)} aria-label="새 옵션" className="w-full">
            <option value="">바꿀 옵션 고르기</option>
            {choices.map((c) => (
              <option key={c.option} value={c.option} disabled={c.current || c.stock < qty}>
                {c.option} · {c.current ? "지금 옵션" : stockText(c)}{!c.current && !c.sold_out && c.stock < qty ? ` (주문 수량 ${qty}개보다 적음)` : ""}
              </option>
            ))}
          </Select>
          <Button className="min-h-9 px-4 py-1" disabled={q.busy || !option}
            onClick={() => q.exec("option", { option }, `옵션을 '${option}'(으)로 바꿀까요? 가격은 같고, 재고가 ${qty}개 옮겨져요.`)}>{q.busy ? <Spinner /> : "옵션 변경"}</Button>
        </>
      )}
      {action === "partial_cancel" && (
        <>
          <p>{qty}개 중 몇 개를 취소할까요? 취소한 만큼 결제가 부분 취소되고, 열린 취소 요청은 처리 완료돼요.</p>
          <div className="flex items-center gap-2">
            <Select value={String(count)} onChange={(e) => setCount(Number(e.target.value))} aria-label="취소할 수량">
              {Array.from({ length: qty - 1 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n}개 ({won(((o.unit_price ?? 0) * n) || null)})</option>)}
            </Select>
            <Button className="min-h-9 px-4 py-1" disabled={q.busy}
              onClick={() => {
                // 서버(order_actions)와 같은 계산: 무료배송(3만원 이상) 주문이 3만원 미만이 되면 배송비 3,000원 차감
                const unit = Math.floor((o.amount ?? 0) / qty), left = (o.amount ?? 0) - unit * count;
                const fee = (o.amount ?? 0) >= 30000 && left < 30000 ? 3000 : 0;
                q.exec("partial_cancel", { count }, `${qty}개 중 ${count}개를 취소할까요?\n환불(승인 취소) ${won(unit * count - fee)}`
                  + (fee ? ` · 남은 금액이 3만원 미만이 되어 배송비 ${won(fee)} 차감` : ""));
              }}>{q.busy ? <Spinner /> : `${count}개 취소`}</Button>
          </div>
        </>
      )}
      {action === "return" && (
        <>
          <Select value={reason} onChange={(e) => setReason(e.target.value as keyof typeof RETURN_FEE)} aria-label="반품 사유" className="w-full">
            <option value="단순 변심" disabled={!o.returnable}>단순 변심{o.returnable ? "" : " (7일 지남)"}</option>
            <option value="불량·오배송">불량·오배송</option>
          </Select>
          <p className="text-xs text-muted">1~3영업일 안에 택배 기사 방문 · {RETURN_FEE[reason]}</p>
          <Button className="min-h-9 px-4 py-1" disabled={q.busy}
            onClick={() => q.exec("return", { reason }, `${reason} 반품 회수를 접수할까요?`)}>{q.busy ? <Spinner /> : "회수 접수"}</Button>
        </>
      )}
      {action === "exchange_fee" && (
        <>
          <p>단순 변심 교환은 왕복 배송비 <b>6,000원</b>을 받아요 (불량·오배송이면 받지 않아요). 받은 뒤 회수를 접수해 주세요.</p>
          {o.exchange_fee?.status === "요청" && <p className="text-xs text-amber-700">결제 요청을 보냈어요. 고객이 문의 화면에서 결제하면 '받음'으로 바뀌어요.</p>}
          <div className="flex flex-wrap gap-1.5">
            <Button className="min-h-9 px-3 py-1" disabled={q.busy || (o.points_balance ?? 0) < 6000}
              onClick={() => q.exec("exchange_fee", { method: "points" }, `고객 적립금에서 6,000원을 차감할까요? (잔액 ${won(o.points_balance ?? 0)})\n고객이 동의했을 때만 진행해 주세요.`)}>
              {q.busy ? <Spinner /> : `적립금으로 차감 (잔액 ${won(o.points_balance ?? 0)})`}
            </Button>
            {!o.exchange_fee && (
              <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={q.busy}
                onClick={() => q.exec("exchange_fee", { method: "request" }, "고객에게 교환 배송비 6,000원 결제를 요청할까요?\n고객 문의 화면에 [교환 배송비 결제] 버튼이 생겨요.")}>
                결제 요청 보내기
              </Button>
            )}
          </div>
          {(o.points_balance ?? 0) < 6000 && <p className="text-xs text-muted">적립금이 6,000원보다 적어 결제 요청으로 받아요.</p>}
        </>
      )}
      {q.error && <Alert>{q.error}</Alert>}
    </div>
  );
}

/** 주문 바로 처리: 지금 주문 상태에서 할 수 있는 것만 버튼으로 (배송지·옵션 변경·부분 취소 = 출고 전, 중복 승인 취소, 반품 회수 접수) */
export function OrderActions({ o, inquiryId, onDone }: { o: OrderCard; inquiryId: number; onDone: (msg: string) => void }) {
  const q = useQuickAction(inquiryId, onDone);
  const beforeShipping = o.order_status === "결제 완료" || o.order_status === "상품 준비 중";
  const qty = o.quantity ?? 1;
  const choices = o.option_choices ?? [];
  const canReturn = o.order_status === "배송 완료" && !o.return_requested_at && !!o.defect_return_until && new Date(o.defect_return_until).getTime() > Date.now();
  // 교환 배송비: 배송 완료 + 단순 변심 기한(7일) 안 + 아직 받지 않음
  const canExchangeFee = o.order_status === "배송 완료" && !!o.returnable && o.exchange_fee?.status !== "완료";
  const feeText = exchangeFeeText(o);
  if (!beforeShipping && !o.duplicate_payment && !canReturn && !canExchangeFee && !feeText) return null;
  return (
    <div className="mt-3 rounded-xl border border-primary/20 bg-primary-soft/40 p-3">
      <p className="mb-2 text-sm font-semibold text-ink">바로 처리 <span className="font-normal text-muted">· 지금 주문 상태에서 할 수 있는 것</span></p>
      <div className="flex flex-wrap gap-1.5">
        {o.duplicate_payment && <ActionButton label="중복 승인 1건 취소" tone="danger" active={q.open === "duplicate_cancel"} onClick={() => q.toggle("duplicate_cancel")} />}
        {beforeShipping && <ActionButton label="배송지 변경" active={q.open === "address"} onClick={() => q.toggle("address")} />}
        {beforeShipping && choices.length > 0 && <ActionButton label="옵션 변경" active={q.open === "option"} onClick={() => q.toggle("option")} />}
        {beforeShipping && qty > 1 && <ActionButton label="부분 취소" active={q.open === "partial_cancel"} onClick={() => q.toggle("partial_cancel")} />}
        {canReturn && <ActionButton label="반품 회수 접수" active={q.open === "return"} onClick={() => q.toggle("return")} />}
        {canExchangeFee && <ActionButton label="교환 배송비 받기" active={q.open === "exchange_fee"} onClick={() => q.toggle("exchange_fee")} />}
      </div>
      {feeText && <p className="mt-2 text-xs text-body">{feeText}</p>}
      {q.open && <ActionForm key={q.open} action={q.open} o={o} q={q} />}
    </div>
  );
}

/** 요청 카드 안에서 바로 처리: 요청을 승인하기 전에 먼저 할 일(반품 회수 접수)이나 대신할 일(부분 취소·옵션 변경)을 그 자리에서 펼침.
 *  주문 정보의 [바로 처리]와 같은 서버 처리·확인창 */
export function InlineAction({ action, label, o, inquiryId, onDone }: {
  action: QuickAction; label: string; o: OrderCard; inquiryId: number; onDone: (msg: string) => void;
}) {
  const q = useQuickAction(inquiryId, onDone);
  return (
    <div>
      <ActionButton label={label} active={q.open === action} onClick={() => q.toggle(action)} />
      {q.open === action && <ActionForm action={action} o={o} q={q} />}
    </div>
  );
}

/** 고객 바로 처리: 보상 적립금(상담원 3,000원까지), 사과 쿠폰 */
export function CustomerActions({ inquiryId, isAdmin, onDone }: { inquiryId: number; isAdmin: boolean; onDone: (msg: string) => void }) {
  const q = useQuickAction(inquiryId, onDone);
  const limit = isAdmin ? 50000 : 3000;
  const [amount, setAmount] = useState(1000);
  const [reason, setReason] = useState("");
  const [coupon, setCoupon] = useState(COUPON_CHOICES[0].name);
  return (
    <div className="mt-3 border-t border-hairline pt-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-sm font-semibold text-body">보상</span>
        <ActionButton label="적립금 지급" active={q.open === "points"} onClick={() => q.toggle("points")} />
        <ActionButton label="쿠폰 발급" active={q.open === "coupon"} onClick={() => q.toggle("coupon")} />
      </div>
      {q.open === "points" && (
        <div className="mt-2 space-y-2 rounded-lg bg-surface-soft p-2.5 text-sm">
          <div className="flex items-center gap-2">
            <Input type="number" min={100} max={limit} step={100} value={amount} onChange={(e) => setAmount(Number(e.target.value))}
              className="min-h-9! w-28! flex-none" aria-label="적립금" />
            <span className="text-xs text-muted">원 · 1회 {limit.toLocaleString()}원까지{isAdmin ? "" : " (더 큰 금액은 관리자)"}</span>
          </div>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={50} placeholder="사유 (예: 배송 지연 사과, 만료 적립금 복구)" aria-label="사유" />
          <Button className="min-h-9 px-4 py-1" disabled={q.busy || amount < 100 || amount > limit}
            onClick={() => q.exec("points", { amount, reason: reason.trim() || "상담 보상" }, `적립금 ${amount.toLocaleString()}원을 지급할까요?`)}>{q.busy ? <Spinner /> : "지급"}</Button>
        </div>
      )}
      {q.open === "coupon" && (
        <div className="mt-2 space-y-2 rounded-lg bg-surface-soft p-2.5 text-sm">
          <Select value={coupon} onChange={(e) => setCoupon(e.target.value)} aria-label="쿠폰" className="w-full">
            {COUPON_CHOICES.map((c) => <option key={c.name} value={c.name} disabled={c.adminOnly && !isAdmin}>{c.name} · {c.note}</option>)}
          </Select>
          <Button className="min-h-9 px-4 py-1" disabled={q.busy}
            onClick={() => q.exec("coupon", { coupon }, `'${coupon}'을(를) 발급할까요? (30일)`)}>{q.busy ? <Spinner /> : "발급"}</Button>
        </div>
      )}
      {q.error && <div className="mt-2"><Alert>{q.error}</Alert></div>}
    </div>
  );
}
