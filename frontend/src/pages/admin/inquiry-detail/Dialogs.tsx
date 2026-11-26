// 문의 상세의 창: 완료 처리(종료 사유), 다른 상담원에게 넘기기
import { useState } from "react";
import Modal from "../../../components/Modal";
import { Button, Select, cx } from "../../../components/ui";
import type { User } from "../../../services/types";
import { staffLabel } from "../../../services/types";

export const CLOSE_REASONS = ["중복 문의", "스팸·광고", "고객 철회", "전화로 안내", "기타"] as const;
export const ANSWERED = "답변으로 해결";

/** 완료 처리: 언제나 이 창을 거침 (사유는 처리 이력에 남음)
 *  - 답변을 보낸 문의: '답변으로 해결'이 기본 선택 (고객 화면은 그대로 '답변 완료')
 *  - 답변 없이 끝내는 문의: 사유를 꼭 고름 (고객 화면에 '종료됨'과 사유에 맞는 안내) */
export function CloseDialog({ answered, onClose, onDone }: { answered: boolean; onClose: () => void; onDone: (reason: string) => void }) {
  const [reason, setReason] = useState<string>(answered ? ANSWERED : "");
  const reasons = answered ? [ANSWERED, ...CLOSE_REASONS] : CLOSE_REASONS;
  return (
    <Modal title={answered ? "완료 처리" : "답변 없이 완료 처리"} onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>취소</Button>
        <Button disabled={!reason} onClick={() => onDone(reason)}>완료 처리</Button>
      </>}>
      <p>
        {answered
          ? "이 문의를 완료로 바꿀까요? 어떻게 끝났는지 골라 주세요. 고객이 추가 문의를 남기면 다시 열려요."
          : "고객에게 답변을 보내지 않고 끝내는 이유를 골라 주세요. 고객 화면에는 '종료됨'으로 보여요."}
      </p>
      {answered && reason !== ANSWERED && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">이 사유를 고르면 고객 화면에 '종료됨'과 안내가 보여요.</p>
      )}
      <div className="grid grid-cols-2 gap-2">
        {reasons.map((r) => (
          <label key={r} className={cx("flex cursor-pointer items-center gap-2 rounded-xl border px-3 py-2",
            reason === r ? "border-primary bg-primary-soft" : "border-hairline hover:bg-surface-soft")}>
            <input type="radio" name="close-reason" checked={reason === r} onChange={() => setReason(r)} />{r}
          </label>
        ))}
      </div>
    </Modal>
  );
}

/** 넘기기: 다른 상담원에게 인계 (인계 메모 필수 → 공유 메모로 남고, 받는 사람에게 🔔 배정 알림) */
export function HandoverDialog({ staff, meId, onClose, onDone }: {
  staff: User[]; meId: number; onClose: () => void; onDone: (to: number, memo: string) => void;
}) {
  const [to, setTo] = useState("");
  const [memo, setMemo] = useState("");
  const others = staff.filter((u) => u.id !== meId);
  return (
    <Modal title="다른 상담원에게 넘기기" onClose={onClose}
      footer={<>
        <Button variant="ghost" onClick={onClose}>취소</Button>
        <Button disabled={!to || memo.trim().length < 2} onClick={() => onDone(Number(to), memo.trim())}>넘기기</Button>
      </>}>
      <label className="block space-y-1">
        <span className="font-semibold text-ink">받는 사람</span>
        <Select value={to} onChange={(e) => setTo(e.target.value)} className="w-full" aria-label="받는 사람">
          <option value="">고르기</option>
          {others.map((u) => <option key={u.id} value={u.id}>{staffLabel(u)}</option>)}
        </Select>
      </label>
      <label className="block space-y-1">
        <span className="font-semibold text-ink">인계 메모 (필수)</span>
        <textarea value={memo} onChange={(e) => setMemo(e.target.value)} maxLength={500} aria-label="인계 메모"
          className="min-h-24 w-full rounded-xl border border-hairline bg-white px-3 py-2 outline-none focus:border-primary"
          placeholder="지금까지 한 일과 남은 일 (예: 택배사 분실 조사 요청함, 회신 오면 재발송 안내)" />
      </label>
      <p className="text-xs text-muted">메모는 상담원 공유 메모에 '[인계]'로 남아요. 넘긴 뒤에는 이 문의를 볼 수 없어요.</p>
    </Modal>
  );
}
