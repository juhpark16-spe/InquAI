// 문의 상세 오른쪽 '취소·교환·반품 요청' 카드: 승인·반려, 환불 계좌, 반품 회수 접수
import { useState } from "react";
import { confirmDialog } from "../../../components/ConfirmDialog";
import { daysLeft, won } from "../../../components/OrderParts";
import { TICKET_KIND, ticketKind } from "../../../services/labels";
import { Alert, Badge, Button, Input, Spinner, cx, formatDate, monthDay } from "../../../components/ui";
import { errorMessage, inquiryApi } from "../../../services/api";
import type { InquiryDetail } from "../../../services/types";
import { Card, insertIntoReply } from "./parts";
import { InlineAction } from "./OrderActions";

export const TICKET_ACTIONABLE = ["취소", "교환", "환불"];

/** 결제 수단별 환불(승인 취소) 반영 기간 (정책 F29: 카드 3~5영업일, 계좌이체·간편결제 1~3영업일, 무통장은 환불 계좌로 1~2영업일) */
export function refundTiming(method: string | null | undefined) {
  if (method === "무통장입금") return "고객 환불 계좌로 1~2영업일 (계좌를 먼저 받아야 해요)";
  if (method === "계좌이체" || method === "간편결제") return `${method} 1~3영업일 안에 반영`;
  return `${method ?? "카드"} 3~5영업일 안에 반영 (카드사 사정)`;
}
export const REFUND_ACCOUNT_ASK = "무통장입금으로 결제하셔서 환불받으실 계좌가 필요합니다. 문의 조회(회원은 내 쇼핑 > 내 문의)의 [내용 보충 · 추가 문의]에서 "
  + "'환불 계좌' 칸에 은행·예금주·계좌번호를 입력해 주세요. 개인정보 보호를 위해 계좌번호는 문의 내용에 적지 말아 주세요. 확인 후 1~2영업일 안에 환불해 드리겠습니다.";

/** 환불 계좌 (무통장입금 취소·반품): 받았으면 가려서 + [번호 보기](볼 때마다 작업 기록), 없으면 요청 문구 넣기 */
export function RefundAccountLine({ data }: { data: InquiryDetail }) {
  const [shown, setShown] = useState<{ bank: string; holder: string; number: string } | null>(null);
  const [error, setError] = useState("");
  const acc = data.refund_account;
  if (!acc) {
    return (
      <p className="flex flex-wrap items-center gap-2 rounded-lg bg-white px-2.5 py-1.5 text-xs text-amber-900">
        💳 무통장입금 주문이라 <b>환불 계좌</b>가 필요해요 · 아직 없음
        <button type="button" className="font-semibold text-primary hover:underline" onClick={() => insertIntoReply(REFUND_ACCOUNT_ASK)}>+ 환불 계좌 요청 문구 넣기</button>
      </p>
    );
  }
  return (
    <p className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-white px-2.5 py-1.5 text-xs text-ink">
      💳 환불 계좌 받음 ✓ <span className="font-mono">{shown ? `${shown.bank} ${shown.number} · ${shown.holder}` : `${acc.bank} ${acc.number} · ${acc.holder}`}</span>
      {shown ? (
        <button type="button" className="text-muted hover:underline" onClick={() => setShown(null)}>가리기</button>
      ) : (
        <button type="button" className="font-semibold text-primary hover:underline" title="전체 번호를 볼 때마다 작업 기록에 남아요"
          onClick={() => inquiryApi.refundAccount(data.id).then(setShown).catch((err) => setError(errorMessage(err)))}>번호 보기</button>
      )}
      <span className="w-full text-[11px] text-muted">고객이 '환불 계좌' 칸으로 보낸 계좌예요. AI 초안에는 넘기지 않아요.</span>
      {error && <span className="w-full text-rose-700">{error}</span>}
    </p>
  );
}

/** 반려 사유 자주 쓰는 것 (누르면 입력칸에 채움, 고쳐서 쓸 수 있음) */
export const REJECT_PRESETS: Record<string, string[]> = {
  취소: ["이미 출고되어 취소 대신 반품으로 안내", "고객이 취소 요청을 철회"],
  교환: ["교환할 옵션이 품절이라 반품으로 안내", "교환 기한이 지남", "고객이 교환 요청을 철회"],
  환불: ["반품 기한이 지남", "검수 결과 반품 불가 (사용 흔적)", "고객이 반품 요청을 철회"],
};


/** 접수된 티켓: 취소·교환·반품(서버 값 환불)은 상담원이 승인·반려. 판단에 필요한 정보(요청 내용·회수 상태·교환 재고·환불 기간)를
 *  카드 안에 모으고, 먼저 해야 할 [바로 처리]는 버튼으로 바로 열게 함 */
export function Tickets({ data, onChanged }: { data: InquiryDetail; onChanged: (msg: string) => void }) {
  const [busy, setBusy] = useState<number | null>(null);
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [memo, setMemo] = useState("");
  const [error, setError] = useState("");
  // 반품(단순 변심) 승인: 검수해 보니 불량이면 체크 → 배송비 차감 없이 전액 환불
  const [waiveFor, setWaiveFor] = useState<number | null>(null);   // 체크한 반품 요청 번호 (요청마다 따로)

  async function decide(id: number, status: "승인" | "반려", note?: string) {
    const t = data.tickets.find((x) => x.id === id);
    // 승인은 주문·결제를 바로 바꾸므로 한 번 더 확인 (반려는 사유 입력칸이 확인 단계)
    if (status === "승인" && t) {
      const order = data.order?.found ? data.order : null;
      const what = order ? `${order.order_number}${order.product_name ? ` · ${order.product_name}` : ""}` : "연결된 주문";
      const message = t.ticket_type === "취소"
        ? `${what}\n주문을 취소하고 결제 금액${order?.amount != null ? ` ${won(order.amount)}` : ""}을 전액 환불해요.\n환불: ${refundTiming(order?.payment_method)}\n되돌릴 수 없어요.`
        : t.ticket_type === "환불"
          // 서버가 계산한 환불 예정 금액·반품 사유 (inquiry_context.order_card: 회수 접수 때 고른 사유로 배송비 차감 여부)
          ? (waiveFor === id && order?.return_reason === "단순 변심"
            ? `${what}\n반품 환불을 승인해요. 환불 예정 ${won(order.amount)} (검수 결과 불량: 왕복 배송비를 빼지 않고 전액)`
            : `${what}\n반품 환불을 승인해요. 환불 예정 ${order?.refund_preview != null ? won(order.refund_preview) : "금액 확인 필요"}`
              + (order?.return_reason ? ` (반품 사유: ${order.return_reason}, ${order.return_reason === "단순 변심" ? "왕복 배송비 6,000원 차감" : "배송비 쇼핑몰 부담"})` : ""))
            + `\n회수·검수 뒤 3영업일 안에 환불 처리 · ${refundTiming(order?.payment_method)}`
          : `${what}\n교환을 승인해요. 회수·검수 뒤 2~3영업일 안에 새 상품이 출고돼요 (쇼핑몰에서 진행).`
            + "\n단순 변심 교환이면 왕복 배송비 6,000원은 고객 부담이에요 (불량·오배송은 쇼핑몰 부담).";
      if (!(await confirmDialog({ title: `${ticketKind(t.ticket_type)} 승인`, message,
        confirmLabel: `${ticketKind(t.ticket_type)} 승인`, tone: t.ticket_type === "교환" ? "primary" : "danger" }))) return;
    }
    setError("");
    setBusy(id);
    try {
      await inquiryApi.decideTicket(id, status, note, status === "승인" && t?.ticket_type === "환불" && waiveFor === id);
      setWaiveFor(null);
      setRejecting(null);
      setMemo("");
      onChanged(status === "승인"
        ? "요청을 승인했습니다. [AI 초안 다시 만들기]를 누르면 처리 결과를 넣은 답변 초안을 받을 수 있어요."
        : "요청을 반려했습니다. 반려 사유를 고객에게 안내해 주세요 ([AI 초안 다시 만들기]에 사유가 반영됩니다).");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  const o = data.order?.found ? data.order : null;
  // 처리를 마친 요청은 한 줄로 (승인 대기 요청이 위에)
  const tickets = [...data.tickets].sort((a, b) => Number(b.status === "접수") - Number(a.status === "접수"));
  return (
    <Card title="취소·교환·반품 요청">
      <ul className="space-y-3 text-sm">
        {tickets.map((t) => {
          const actionable = TICKET_ACTIONABLE.includes(t.ticket_type) && t.status === "접수";
          const cancelBlocked = t.ticket_type === "취소" && o && o.cancellable === false;
          // 반품 환불은 [반품 회수 접수](배송 완료·기한 확인 + 사유) 뒤에만 승인 (서버도 같은 조건)
          const refundBlocked = t.ticket_type === "환불" && o && !o.return_requested_at;
          // 교환: 배송 완료 + 불량·오배송 기한(30일) 안이어야 (서버 tickets.py 와 같은 조건)
          const exchangeLate = !!o?.defect_return_until && new Date(o.defect_return_until).getTime() < Date.now();
          const exchangeBlocked = t.ticket_type === "교환" && o && (o.order_status !== "배송 완료" || exchangeLate);
          const others = (o?.option_choices ?? []).filter((c) => !c.current);
          const inStock = others.filter((c) => !c.sold_out);
          if (!actionable) {
            return (
              <li key={t.id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 rounded-xl border border-hairline px-3 py-2">
                <span className="font-semibold text-ink">#{t.id} {ticketKind(t.ticket_type)}</span>
                <Badge value={t.status} />
                {t.handled_at && <span className="text-xs text-muted">{formatDate(t.handled_at)}</span>}
                {t.memo && <span className="w-full text-xs text-slate-600">메모: {t.memo}</span>}
              </li>
            );
          }
          return (
            <li key={t.id} className="rounded-xl border border-amber-300 bg-amber-50/60 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-ink">#{t.id} {ticketKind(t.ticket_type)}
                  {TICKET_KIND[t.ticket_type] && <span className="ml-1.5 text-xs font-normal text-muted">{TICKET_KIND[t.ticket_type].refund}</span>}</span>
                <Badge value={t.status} />
              </div>
              {/* 요청 내용 (AI가 문의에서 접수한 사유) */}
              {t.reason && <p className="mt-1 line-clamp-2 text-xs text-body" title={t.reason}>요청: {t.reason}</p>}
              <div className="mt-2 space-y-2">
                {t.ticket_type === "취소" && o && (
                  <>
                    <p className={cx("text-sm", cancelBlocked ? "text-rose-700" : "text-emerald-700")}>
                      {cancelBlocked ? `주문이 '${o.order_status}' 상태라 취소할 수 없어요 → 반려하고 반품으로 안내`
                        : `출고 전(${o.order_status})이라 승인하면 바로 취소 · 환불: ${refundTiming(o.payment_method)}`}
                    </p>
                    {!cancelBlocked && o.payment_method === "무통장입금" && <RefundAccountLine data={data} />}
                    {/* 색상·사이즈를 잘못 골라 취소하려는 경우: 취소 대신 옵션 변경으로 해결 (옵션 변경하면 이 요청도 함께 처리됨) */}
                    {!cancelBlocked && inStock.length > 0 && (
                      <p className="flex flex-wrap items-center gap-2 rounded-lg bg-white px-2.5 py-1.5 text-xs text-ink">
                        색상·사이즈 때문이라면 취소 없이 옵션을 바꿀 수 있어요 (재고 있는 옵션 {inStock.length}개).
                      </p>
                    )}
                    {!cancelBlocked && inStock.length > 0 && (
                      <InlineAction action="option" label="옵션 변경 (취소 대신)" o={o} inquiryId={data.id} onDone={onChanged} />
                    )}
                    {!cancelBlocked && (o.quantity ?? 1) > 1 && (
                      <p className="flex flex-wrap items-center gap-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-sm text-amber-900">
                        ⚠ {o.quantity}개 주문이에요. 승인하면 <b>주문 전체</b>가 취소돼요. 일부만 취소하려면 아래 [부분 취소]를 쓰세요 (이 요청도 함께 처리돼요).
                      </p>
                    )}
                    {!cancelBlocked && (o.quantity ?? 1) > 1 && (
                      <InlineAction action="partial_cancel" label="부분 취소" o={o} inquiryId={data.id} onDone={onChanged} />
                    )}
                  </>
                )}
                {t.ticket_type === "교환" && o && (
                  <>
                    <p className={cx("text-sm", exchangeBlocked ? "text-rose-700" : "text-emerald-700")}>
                      {o.order_status !== "배송 완료" ? `주문이 '${o.order_status}' 상태라 교환할 수 없어요 (배송 완료 후에만)`
                        : exchangeLate ? "배송 완료 후 30일이 지나 교환할 수 없어요 → 반려하고 안내"
                          : `교환 가능 · 단순 변심 ${o.return_until ? daysLeft(o.return_until) : "-"} (왕복 배송비 6,000원 고객 부담) · 불량·오배송 ${o.defect_return_until ? daysLeft(o.defect_return_until) : "-"}`}
                    </p>
                    {others.length > 0 && (
                      <p className={cx("rounded-lg px-2.5 py-1.5 text-xs", inStock.length ? "bg-white text-ink" : "bg-rose-50 font-semibold text-rose-700")}>
                        {inStock.length
                          ? <>교환할 수 있는 옵션: {inStock.map((c) => `${c.option}(${c.stock}개)`).join(" · ")}</>
                          : "다른 옵션이 모두 품절이라 교환할 수 없어요 → 반려하고 반품(환불)으로 안내 (정책 F32)"}
                      </p>
                    )}
                  </>
                )}
                {t.ticket_type === "환불" && o && (
                  <>
                    {o.payment_method === "무통장입금" && <RefundAccountLine data={data} />}
                    {refundBlocked ? (
                      <>
                        <p className="text-sm text-amber-800">먼저 반품 회수를 접수해 주세요 (배송 완료·반품 기한 확인, 반품 사유 기록 → 그다음 승인)</p>
                        <InlineAction action="return" label="반품 회수 접수" o={o} inquiryId={data.id} onDone={onChanged} />
                      </>
                    ) : (
                      <p className="text-sm text-emerald-700">
                        회수 접수 {monthDay(o.return_requested_at)}{o.return_reason ? ` (${o.return_reason})` : ""}
                        {" → "}{o.picked_up_at ? `회수 완료 ${monthDay(o.picked_up_at)}` : <span className="text-amber-700">회수 전</span>}
                        {" · "}승인하면 환불 예정이 기록돼요
                      </p>
                    )}
                  </>
                )}
                {/* 회수 접수 때 '단순 변심'이었어도 검수해 보니 불량이면 배송비는 쇼핑몰 부담 (정책 F17) */}
                {t.ticket_type === "환불" && o && !refundBlocked && o.return_reason === "단순 변심" && (
                  <label className="flex items-start gap-2 rounded-lg bg-white px-2.5 py-1.5 text-sm text-ink">
                    <input type="checkbox" className="mt-0.5" checked={waiveFor === t.id} onChange={(e) => setWaiveFor(e.target.checked ? t.id : null)} />
                    <span>검수 결과 불량 → 배송비 차감 없이 전액 환불
                      <span className="block text-xs text-muted">
                        {waiveFor === t.id ? `환불 ${won(o.amount)} (전액)` : `지금: 환불 ${won(o.refund_preview ?? o.amount)} (왕복 배송비 6,000원 차감)`}
                        {!o.picked_up_at && " · 아직 회수 전이라 검수 전이에요"}
                      </span></span>
                  </label>
                )}
                {rejecting === t.id ? (
                  <div className="space-y-2">
                    <div className="flex flex-wrap gap-1.5">
                      {(REJECT_PRESETS[t.ticket_type] ?? []).map((p) => (
                        <button key={p} type="button" onClick={() => setMemo(p)}
                          className={cx("rounded-full border px-2 py-0.5 text-xs", memo === p ? "border-primary bg-primary-soft text-primary" : "border-hairline bg-white text-body hover:border-primary")}>
                          {p}
                        </button>
                      ))}
                    </div>
                    <Input autoFocus placeholder="반려 사유 (위에서 고르거나 직접 입력)" maxLength={500}
                      value={memo} onChange={(e) => setMemo(e.target.value)} />
                    {/* 버튼 순서는 다른 확인창과 같게: 왼쪽 취소, 오른쪽 실행 */}
                    <div className="flex gap-2">
                      <Button variant="ghost" className="min-h-9 px-3 py-1" onClick={() => { setRejecting(null); setMemo(""); }}>취소</Button>
                      <Button variant="danger" className="min-h-9 flex-1 px-3 py-1" disabled={busy === t.id || !memo.trim()}
                        onClick={() => decide(t.id, "반려", memo)}>{busy === t.id ? <Spinner /> : "반려"}</Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <Button className="min-h-9 flex-1 px-3 py-1" disabled={busy === t.id || !!cancelBlocked || !!refundBlocked || !!exchangeBlocked}
                      onClick={() => decide(t.id, "승인")}>{busy === t.id ? <Spinner /> : `${ticketKind(t.ticket_type)} 승인`}</Button>
                    <Button variant="ghost" className="min-h-9 flex-1 px-3 py-1" disabled={busy === t.id}
                      onClick={() => { setRejecting(t.id); setMemo(cancelBlocked ? REJECT_PRESETS["취소"][0] : ""); }}>반려</Button>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {error && <div className="mt-2"><Alert>{error}</Alert></div>}
    </Card>
  );
}
