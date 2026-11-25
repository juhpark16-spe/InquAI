// 환불 계좌 칸 (무통장입금 주문을 취소·반품할 때): 은행 / 예금주 / 계좌번호
// 문의 글과 따로 보내고 AI에는 넘기지 않음 (backend/services/refund_account.py). 문의하기·추가 문의가 함께 씀
import { Input, Select, cx } from "./ui";
import type { RefundAccountInput } from "../services/types";

export const BANKS = ["국민은행", "신한은행", "우리은행", "하나은행", "농협은행", "기업은행", "SC제일은행", "카카오뱅크", "토스뱅크", "케이뱅크",
  "새마을금고", "우체국", "수협은행", "부산은행", "대구은행", "광주은행", "경남은행", "전북은행", "씨티은행"];
export const EMPTY_REFUND: RefundAccountInput = { bank: "", holder: "", number: "" };
/** 취소·반품·환불 이야기인지 (비회원은 결제 수단을 알 수 없어 글로 판단: 그럴 때만 환불 계좌 칸을 보여 줌) */
export const REFUND_WORDS = /취소|반품|환불/;

/** 세 칸이 모두 맞게 채워졌으면 보낼 값, 하나도 안 채웠으면 null, 덜 채웠거나 틀리면 "invalid" */
export function refundValue(v: RefundAccountInput): RefundAccountInput | null | "invalid" {
  const digits = v.number.replace(/\D/g, "");
  if (!v.bank && !v.holder.trim() && !digits) return null;
  if (!v.bank || v.holder.trim().length < 2 || digits.length < 10 || digits.length > 16 || /[^\d\s-]/.test(v.number)) return "invalid";
  return { bank: v.bank, holder: v.holder.trim(), number: digits };
}

/** 체크 칸 + 펼쳐지는 입력칸 (문의하기의 '파손·불량' 체크와 같은 모양). 체크를 풀면 닫히고 입력한 값도 지움 */
export function RefundAccountToggle({ checked, onToggle, value, onChange, disabled, autoNote }: {
  checked: boolean; onToggle: (on: boolean) => void; value: RefundAccountInput; onChange: (v: RefundAccountInput) => void;
  disabled?: boolean; autoNote?: string;
}) {
  return (
    <div className="space-y-2">
      <label className={cx("flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm",
        checked ? "border-primary/30 bg-primary-soft/50" : "border-hairline bg-white")}>
        <input type="checkbox" className="mt-0.5" checked={checked} disabled={disabled}
          onChange={(e) => { onToggle(e.target.checked); if (!e.target.checked) onChange(EMPTY_REFUND); }} />
        <span>
          <span className="font-semibold text-ink">무통장입금으로 결제한 주문을 취소·반품해요</span>
          {autoNote && <span className="ml-1 text-xs text-primary">· {autoNote}</span>}
          <span className="block text-xs text-muted">체크하면 환불받을 계좌를 입력하는 칸이 열려요. 계좌번호는 본문에 쓰지 말고 이 칸에만 넣어 주세요.</span>
        </span>
      </label>
      {checked && <RefundAccountFields value={value} onChange={onChange} disabled={disabled} bare />}
    </div>
  );
}

export default function RefundAccountFields({ value, onChange, disabled, bare }: {
  value: RefundAccountInput; onChange: (v: RefundAccountInput) => void; disabled?: boolean; bare?: boolean;
}) {
  const state = refundValue(value);
  return (
    <div className="space-y-2 rounded-xl border border-primary/20 bg-primary-soft/30 p-3 text-sm">
      {!bare && <p className="font-semibold text-ink">환불 계좌 <span className="font-normal text-muted">(무통장입금으로 결제한 주문을 취소·반품할 때)</span></p>}
      <p className="text-xs text-muted">🔒 계좌번호는 <b>문의 내용에 적지 말고</b> 이 칸에만 입력해 주세요. 상담원만 확인하고, 화면에는 가려서 보여요.</p>
      <div className="grid gap-2 sm:grid-cols-[9rem_8rem_1fr]">
        <Select value={value.bank} onChange={(e) => onChange({ ...value, bank: e.target.value })} disabled={disabled} aria-label="환불 받을 은행">
          <option value="">은행 고르기</option>
          {BANKS.map((b) => <option key={b} value={b}>{b}</option>)}
        </Select>
        <Input value={value.holder} onChange={(e) => onChange({ ...value, holder: e.target.value })} maxLength={30}
          placeholder="예금주" aria-label="예금주" disabled={disabled} />
        <Input value={value.number} onChange={(e) => onChange({ ...value, number: e.target.value })} maxLength={30} inputMode="numeric"
          placeholder="계좌번호 (숫자만, 하이픈 가능)" aria-label="계좌번호" autoComplete="off" disabled={disabled} />
      </div>
      {state === "invalid" && <p role="alert" className="text-xs font-medium text-rose-600">은행·예금주(2자 이상)·계좌번호(숫자 10~16자리)를 모두 적어 주세요.</p>}
    </div>
  );
}
