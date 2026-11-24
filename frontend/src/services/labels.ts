// AI 처리 기록을 관리자가 읽는 말로 (AI 실행 로그·문의 상세 'AI 처리 상세'·대시보드 공통)
// 서버·DB 값(selected_tool, decided_by)은 그대로 두고 화면에 보이는 이름만 바꿈 (backend/services/inquiry_context.py 의 처리 이력도 같은 말)

/** AI 처리 작업 (서버 값 → 화면 이름, 설명) */
export const TOOL_LABEL: Record<string, { label: string; help: string }> = {
  "FAQ 검색": { label: "FAQ로 답변", help: "FAQ를 근거로 자동 답변하거나 답변 초안을 씀" },
  "배송 조회": { label: "배송 조회", help: "주문의 배송 상태를 확인함" },
  "티켓 접수": { label: "처리 요청 접수", help: "취소·교환·환불 처리 요청서(티켓)를 만들어 상담원이 승인하게 함" },
  "상담원 이관": { label: "상담원 이관", help: "AI가 처리하지 않고 상담원에게 넘김" },
};
export const toolLabel = (tool: string | null | undefined) => (tool ? TOOL_LABEL[tool]?.label ?? tool : "-");

/** 누가 판단했나: LLM(AI가 내용을 읽고) / 규칙(긴급·확신 낮음 등은 AI를 기다리지 않고 바로) */
export const BY_LABEL: Record<string, string> = { LLM: "AI가 판단", "규칙": "규칙으로 바로" };
export const byLabel = (by: string | null | undefined) => (by ? BY_LABEL[by] ?? by : "-");

/** AI가 유형을 이만큼 확신하지 못하면 상담원이 유형을 확인 */
export const LOW_CONFIDENCE = 0.8;
export const LOW_CONFIDENCE_TEXT = "유형 판단 불확실";
export const LOW_CONFIDENCE_HELP = "AI가 문의 유형을 80% 미만으로 확신해 자동 답변하지 않고 상담원에게 넘겼어요. 유형이 맞는지 확인해 주세요.";

/** '미완료'의 이유 (도구 결과의 message: "주문번호 없음 (상담원이 고객에게 확인)" → "주문번호 없음") */
export function failReason(output: Record<string, unknown> | null | undefined): string {
  const message = typeof output?.message === "string" ? output.message : "";
  return message.replace(/\s*\(.*\)\s*$/, "") || "이유 기록 없음";
}

/** 처리 요청(티켓) 종류: 서버 값 '환불'은 반품 후 환불이라 화면에서는 '반품'으로.
 *  취소·반품 모두 승인하면 환불이 진행됨 (취소 = 카드 승인 취소로 바로 전액, 반품 = 회수·검수 뒤 3영업일 안) */
export const TICKET_KIND: Record<string, { label: string; refund: string }> = {
  취소: { label: "취소", refund: "바로 전액 환불" },
  교환: { label: "교환", refund: "환불 없음" },
  환불: { label: "반품", refund: "회수 후 환불" },
};
export const ticketKind = (type: string) => TICKET_KIND[type]?.label ?? type;
