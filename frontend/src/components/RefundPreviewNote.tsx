// 문의하기의 환불 미리 보기: 취소·반품·교환 이야기를 쓰면 돌려받을 금액·배송비를 미리 보여 줌 (동의 체크 없음).
// 회원은 고른 주문의 실제 금액(GET /api/shop/orders/{번호}/refund-preview), 비회원은 주문을 알 수 없어 정책 한 줄만.
// 실제 금액은 상담원이 주문·검수 결과로 확정 (backend/services/refund_preview.py)
import { useEffect, useState } from "react";

import { shopApi } from "../services/api";
import type { RefundPreview } from "../services/types";
import { monthDay } from "./ui";

export const MONEY_WORDS = /취소|반품|환불|교환/;
const won = (n: number) => `${n.toLocaleString()}원`;

export default function RefundPreviewNote({ member, orderNumber, damage, exchange }: {
  member: boolean; orderNumber: string; damage: boolean; exchange: boolean;
}) {
  const [p, setP] = useState<{ key: string; data: RefundPreview | null } | null>(null);
  useEffect(() => {
    if (!member || !orderNumber) return;
    let live = true;   // 주문을 빨리 바꾸면 늦게 온 앞 주문의 응답이 덮지 않게
    shopApi.refundPreview(orderNumber).then((data) => { if (live) setP({ key: orderNumber, data }); })
      .catch(() => { if (live) setP({ key: orderNumber, data: null }); });
    return () => { live = false; };
  }, [member, orderNumber]);
  const data = p?.key === orderNumber ? p.data : null;

  const lines: string[] = [];
  if (!member || !orderNumber) {
    lines.push("단순 변심 반품은 왕복 배송비 6,000원을 환불 금액에서 빼고, 파손·불량·오배송은 전액 환불해 드려요.");
    if (exchange) lines.push("단순 변심 교환은 왕복 배송비 6,000원이 들어요 (적립금 차감 또는 문의 화면에서 결제).");
    lines.push("출고 전 부분 취소로 남은 금액이 3만원 미만이 되면 처음 배송비 3,000원을 빼고 환불돼요.");
  } else if (!data || !data.kind) {
    return null;
  } else if (data.kind === "cancel") {
    lines.push(`출고 전이라 바로 취소할 수 있어요. 전체 취소: ${won(data.amount)} 전액 환불`);
    for (const r of data.partial) {
      lines.push(`${r.count}개만 취소: ${won(r.refund)} 환불` + (r.fee ? ` (남은 금액이 3만원 미만이 되어 배송비 ${won(r.fee)} 차감)` : ""));
    }
  } else {
    const until = (d: string | null) => (d ? ` · ${monthDay(d)}까지` : " · 받으신 날부터");
    if (damage) {
      if (data.defect_refund !== null) lines.push(`파손·불량·오배송이면 배송비 없이 전액 ${won(data.defect_refund)} 환불${until(data.defect_until)}`);
    } else {
      if (data.change_refund !== null) lines.push(`단순 변심 반품: ${won(data.change_refund)} 환불 (왕복 배송비 6,000원 차감)${until(data.change_until)}`);
      else lines.push("단순 변심 반품 기한(받은 날부터 7일)이 지났어요.");
      if (data.defect_refund !== null) lines.push(`파손·불량·오배송이면 전액 ${won(data.defect_refund)} 환불`);
    }
    if (exchange && !damage) lines.push("단순 변심 교환은 왕복 배송비 6,000원이 들어요 (적립금 차감 또는 문의 화면에서 결제).");
  }
  return (
    <div className="space-y-1 rounded-xl border border-sky-200 bg-sky-50/70 px-3 py-2.5 text-sm" aria-live="polite">
      <p className="font-semibold text-sky-900">💡 {member && data ? "이 주문을 취소·반품하면" : "취소·반품할 때 배송비는 이렇게 돼요"}</p>
      <ul className="list-disc space-y-0.5 pl-5 text-body">
        {lines.map((l) => <li key={l}>{l}</li>)}
      </ul>
      <p className="text-xs text-muted">
        {member && data ? `환불은 ${data.refund_timing}. ` : ""}예정 금액이에요. 실제 금액은 주문과 검수 결과를 보고 상담원이 확인해 드려요.
      </p>
    </div>
  );
}
