// 문의 상세 오른쪽 '주문 정보' 카드: 주문 요약·유형별 핵심 칸·주문번호 입력·바로 처리 버튼
import { useState } from "react";
import { Link } from "react-router";
import { useAuth } from "../../../auth/AuthProvider";
import { confirmDialog } from "../../../components/ConfirmDialog";
import { OrderFocus, OrderHead, OrderRows, OrderStatusLine, PaymentList, ShipmentList, StockList, SubFold } from "../../../components/OrderParts";
import { Alert, Badge, Button, Input, Spinner, cx, formatDate } from "../../../components/ui";
import { errorMessage, inquiryApi } from "../../../services/api";
import type { InquiryDetail, OrderCard } from "../../../services/types";
import { Card, insertIntoReply, timeAgo } from "./parts";
import { OrderActions } from "./OrderActions";

/** 주문 한 건의 상세: 상태·배송·취소·반품 가능 기한 */
export const ORDER_CATEGORIES = ["배송", "주문 취소", "교환", "반품·환불", "결제"];   // 주문을 확인해야 상담할 수 있는 유형
export const ORDER_NUMBER_ASK = "정확한 확인을 위해 주문번호(예: 20261103-0042)를 알려 주시겠어요? 마이페이지 > 주문내역에서 확인하실 수 있습니다.";

/** 주문번호 입력·변경: 고객이 빠뜨렸거나 잘못 적은 번호를 상담원이 확인한 번호로 (추가 문의·전화로 받은 번호, 고객 글에 적힌 번호) */
export function OrderNumberFix({ inquiryId, current, hints, onDone, compact }: {
  inquiryId: number; current: string | null; hints: NonNullable<InquiryDetail["order_hints"]>; onDone: (msg: string) => void; compact?: boolean;
}) {
  const [open, setOpen] = useState(!compact);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function apply(number: string) {
    const ok = await confirmDialog({
      title: current ? "주문번호 변경" : "주문번호 지정",
      message: `이 문의의 주문번호를 ${current ? `${current} → ` : ""}${number}(으)로 ${current ? "바꿀까요" : "지정할까요"}?\n주문 정보가 이 번호로 다시 확인되고, 처리 이력에 남아요.`,
      confirmLabel: current ? "변경" : "지정",
    });
    if (!ok) return;
    setError("");
    setBusy(true);
    try {
      await inquiryApi.setOrderNumber(inquiryId, number);
      setValue("");
      onDone(`주문번호를 ${number}(으)로 ${current ? "바꿨어요" : "지정했어요"}. 주문 정보를 다시 확인했어요.`);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mb-3 space-y-2">
      {hints.map((h) => (
        <div key={h.order_number} className="flex flex-wrap items-center gap-2 rounded-xl border border-primary/30 bg-primary-soft/50 px-3 py-2 text-sm">
          <span className="min-w-0 flex-1">
            고객이 적은 주문번호 <b className="font-mono text-ink">{h.order_number}</b>
            <span className="block text-xs text-muted">
              {h.found ? `${h.product_name ?? "주문"} · ${h.email_match ? "본인 주문" : "주문자 이메일이 달라요 (본인 확인 필요)"}` : "이 번호의 주문이 없어요"}
            </span>
          </span>
          {h.found && <Button className="min-h-9 px-3 py-1" disabled={busy} onClick={() => apply(h.order_number)}>이 번호로 확인</Button>}
        </div>
      ))}
      {open ? (
        <div className="flex flex-wrap items-center gap-2">
          <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="20261103-0042" aria-label="주문번호 입력"
            inputMode="numeric" maxLength={30} className="min-h-9! w-44! flex-none py-1.5 font-mono" disabled={busy}
            onKeyDown={(e) => { if (e.key === "Enter" && value.trim()) apply(value.replace(/\s/g, "")); }} />
          <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={busy || !value.trim()} onClick={() => apply(value.replace(/\s/g, ""))}>
            {busy ? <Spinner /> : current ? "주문번호 변경" : "주문번호 지정"}
          </Button>
          <span className="text-xs text-muted">고객에게 받은 번호를 넣으면 주문을 다시 확인해요</span>
        </div>
      ) : (
        <button type="button" onClick={() => setOpen(true)} className="text-xs font-semibold text-primary hover:underline">주문번호 변경</button>
      )}
      {error && <Alert>{error}</Alert>}
    </div>
  );
}

/** 주문 정보: 고객이 적은 주문(크게) + 문의 이메일로 찾은 다른 주문(핵심만 보이고 누르면 상세).
 *  category: 결제 문의면 결제·환불 내역, 배송 문의면 배송 추적을 펼쳐 둠. 주문이 필요한 유형인데 주문번호가 없으면 요청 버튼 */
export function OrderInfo({ o, others, hints, category, needsOrder, inquiryId, onDone, exchanged }: {
  o: OrderCard | null; others: OrderCard[]; hints: NonNullable<InquiryDetail["order_hints"]>; category: string | null; needsOrder: boolean;
  inquiryId: number; onDone: (msg: string) => void; exchanged?: boolean;
}) {
  const { user } = useAuth();
  const canOpen = (assignedTo: number | null | undefined) => user?.role === "admin" || assignedTo === user?.id;   // 상담원은 맡은 문의만
  const [assignError, setAssignError] = useState("");
  // 주문을 확인하지 못한 문의(번호 없음·없는 주문·다른 사람 주문)는 주문번호 입력칸을 펼쳐 두고, 확인된 주문은 [주문번호 변경]만
  const unresolved = !o || !o.found || o.email_match === false;
  const showFix = unresolved ? (needsOrder || !!o || hints.length > 0 || others.length > 0) : true;
  const assign = async (number: string) => {
    if (!(await confirmDialog({ title: "이 주문으로 지정", confirmLabel: "지정",
      message: `이메일로 찾은 주문 ${number}을(를) 이 문의의 주문으로 지정할까요?\n어떤 주문인지 고객에게 확인한 뒤 지정하세요.` }))) return;
    setAssignError("");
    try {
      await inquiryApi.setOrderNumber(inquiryId, number);
      onDone(`주문번호를 ${number}(으)로 지정했어요. 주문 정보를 다시 확인했어요.`);
    } catch (err) {
      setAssignError(errorMessage(err));   // 실패는 빨간 안내로 (성공 안내에 섞이지 않게)
    }
  };
  const payments = o?.payments ?? [];
  const steps = o?.shipment_events ?? [];
  const related = o?.related_inquiries ?? [];
  return (
    <Card title="주문 정보">
      {needsOrder && (
        <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
          <p className="font-semibold">{category} 문의인데 {o ? "주문번호를 찾을 수 없어요" : "주문번호가 없어요"}</p>
          <p className="mt-0.5 text-xs">주문을 확인해야 정확히 안내할 수 있어요.{others.length > 0 && " 아래 이메일로 찾은 주문 중 어느 것인지 고객에게 확인하세요."}</p>
          <button type="button" onClick={() => insertIntoReply(ORDER_NUMBER_ASK)}
            className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-sm font-semibold text-amber-900 hover:bg-amber-100">
            + 주문번호 요청 문구 넣기
          </button>
        </div>
      )}
      {!o && !needsOrder && <p className="text-sm text-muted">주문번호 없이 남긴 문의입니다{category ? ` (${category} 문의라 주문 확인이 꼭 필요하지는 않음)` : ""}.</p>}
      {o && !o.found && (
        <div className="mb-3"><Alert>주문번호 <b className="font-mono">{o.order_number}</b>를 찾을 수 없습니다. 고객에게 주문번호를 다시 확인해 주세요.</Alert></div>
      )}
      {assignError && <div className="mb-3"><Alert>{assignError}</Alert></div>}
      {showFix && unresolved && <OrderNumberFix inquiryId={inquiryId} current={o?.order_number ?? null} hints={hints} onDone={onDone} />}
      {o?.found && (
        <>
          {o.email_match === false && (
            <div className="mb-3"><Alert>문의 이메일과 주문자 이메일이 다릅니다 (주문자: {o.orderer}). 본인 확인 전에는 주문 정보를 안내하지 마세요.</Alert></div>
          )}
          {o.duplicate_payment && (
            <div className="mb-3 rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-700">
              ⚠ 같은 금액이 10분 안에 두 번 승인됐어요 (중복 결제 의심). 아래 결제·환불 내역에서 승인번호를 확인하세요.
            </div>
          )}
          {related.length > 0 && (
            <div className="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <p className="font-semibold">이 주문의 다른 문의 {related.length}건 · 같은 내용을 서로 다르게 안내하지 않게 확인하세요</p>
              <ul className="mt-1 space-y-0.5">
                {related.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-2">
                    {canOpen(r.assigned_to)
                      ? <Link to={`/admin/inquiries/${r.id}`} className="truncate text-primary hover:underline">{r.title}</Link>
                      : <span className="truncate" title="다른 상담원이 맡은 문의예요">{r.title} <span className="text-xs text-muted">(다른 상담원 담당)</span></span>}
                    <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted"><Badge value={r.status} />{timeAgo(r.created_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="mb-3">
            <p className="mb-0.5 text-xs font-semibold text-emerald-700">고객이 문의한 주문</p>
            <OrderHead o={o} />
            {o.option && <p className="text-xs text-muted">옵션: {o.option}</p>}
          </div>
          {/* 한 줄 요약 → 문의 유형에 맞춘 핵심 3~4줄 → 나머지는 '주문 전체 정보'로 접음 (상담에 필요한 것만 먼저) */}
          <OrderStatusLine o={o} exchanged={exchanged} />
          <OrderFocus o={o} category={category} />
          <SubFold title="주문 전체 정보 (결제·날짜·배송지 등)">
            <OrderRows o={o} />
          </SubFold>
          {o.email_match !== false && <OrderActions key={`${o.order_number}-${o.order_status}-${o.quantity}-${o.product_name}-${payments.length}`} o={o} inquiryId={inquiryId} onDone={onDone} />}
          {payments.length > 0 && (
            <SubFold title={`결제·환불 내역 (${payments.length})`}
              open={o.duplicate_payment || category === "결제" || category === "반품·환불" || payments.some((p) => p.kind !== "승인")}>
              <PaymentList o={o} />
            </SubFold>
          )}
          {steps.length > 0 && (
            <SubFold title={`배송 추적 (${steps.length}단계${o.carrier ? ` · ${o.carrier}` : ""})`} open={category === "배송"}>
              <ShipmentList o={o} />
            </SubFold>
          )}
          {(o.option_choices?.length ?? 0) > 0 && (
            <SubFold title={`옵션별 재고 (${o.option_choices!.length})`} open={category === "교환" || category === "상품"}>
              <StockList o={o} />
            </SubFold>
          )}
        </>
      )}

      {others.length > 0 ? (
        <details className={cx("group/others", o?.found && "mt-4 border-t border-hairline pt-3")} open={needsOrder}>
          <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold text-body hover:text-primary">
            {o?.found ? `이 고객의 다른 주문 (${others.length})` : `문의 이메일로 찾은 주문 (${others.length})`}
            <span className="font-normal text-muted"><span className="group-open/others:hidden">펼치기 ▾</span><span className="hidden group-open/others:inline">접기 ▴</span></span>
          </summary>
          {!o?.found && (
            <p className="mt-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              주문번호 없이 이메일로 찾은 주문입니다. 어떤 주문인지, 본인이 맞는지 고객에게 확인한 뒤 안내하세요.
            </p>
          )}
          <ul className="mt-2 space-y-2">
            {others.map((x) => (
              <li key={x.order_number}>
                <details className="group rounded-xl border border-hairline bg-white">
                  <summary className="flex cursor-pointer list-none items-start gap-3 px-3 py-2.5 hover:bg-surface-soft">
                    <div className="min-w-0 flex-1">
                      <OrderHead o={x} />
                      <p className="mt-0.5 text-xs text-muted">
                        {x.shipping_status ?? "배송 정보 없음"} · 주문 {formatDate(x.ordered_at)}
                      </p>
                    </div>
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <Badge value={x.order_status} />
                      <span className="text-xs text-muted"><span className="group-open:hidden">상세 ▾</span><span className="hidden group-open:inline">접기 ▴</span></span>
                    </span>
                  </summary>
                  <div className="border-t border-hairline px-3 py-2.5">
                    <OrderRows o={x} />
                    {(x.payments?.length ?? 0) > 0 && <SubFold title={`결제·환불 내역 (${x.payments!.length})`}><PaymentList o={x} /></SubFold>}
                    {unresolved && (
                      <Button variant="ghost" className="mt-2 min-h-9 px-3 py-1" onClick={() => assign(x.order_number)}>이 주문으로 지정</Button>
                    )}
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </details>
      ) : !o?.found && (
        <p className="mt-1 text-sm text-muted">이 이메일로 된 주문도 없습니다.</p>
      )}
      {!unresolved && o && (
        <div className="mt-3 border-t border-hairline pt-2.5">
          <OrderNumberFix inquiryId={inquiryId} current={o.order_number} hints={hints} onDone={onDone} compact />
        </div>
      )}
    </Card>
  );
}
