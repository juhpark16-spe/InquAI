// 여러 화면이 같이 쓰는 작은 UI 조각
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

export function cx(...names: (string | false | null | undefined)[]) {
  return names.filter(Boolean).join(" ");
}

const fieldBase =
  "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-100 disabled:bg-slate-100";
const inputBase = `w-full ${fieldBase}`;

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputBase, props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputBase, "min-h-32", props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(fieldBase, props.className)} />;
}

export function Button({ variant = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "ghost" | "danger" }) {
  const styles = {
    primary: "bg-indigo-600 text-white hover:bg-indigo-700 disabled:bg-indigo-300",
    ghost: "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:text-slate-400",
    danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
  }[variant];
  return (
    <button {...props} className={cx("whitespace-nowrap rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed", styles, props.className)} />
  );
}

export function Card({ title, children, className }: { title?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-xl border border-slate-200 bg-white p-5 shadow-sm", className)}>
      {title && <h2 className="mb-3 text-sm font-semibold text-slate-900">{title}</h2>}
      {children}
    </section>
  );
}

export function Alert({ kind = "error", children }: { kind?: "error" | "info" | "success"; children: ReactNode }) {
  const styles = {
    error: "border-rose-200 bg-rose-50 text-rose-700",
    info: "border-sky-200 bg-sky-50 text-sky-800",
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  }[kind];
  return <div role={kind === "error" ? "alert" : "status"} className={cx("rounded-lg border px-4 py-3 text-sm", styles)}>{children}</div>;
}

const BADGE: Record<string, string> = {
  // 긴급도
  높음: "bg-rose-100 text-rose-700", 보통: "bg-amber-100 text-amber-800", 낮음: "bg-slate-100 text-slate-600",
  // 상태
  접수: "bg-slate-100 text-slate-600", "자동 처리": "bg-emerald-100 text-emerald-700",
  "검토 대기": "bg-amber-100 text-amber-800", "담당자 처리": "bg-indigo-100 text-indigo-700", 완료: "bg-slate-200 text-slate-700",
  // 처리 방식
  "자동 답변": "bg-emerald-100 text-emerald-700", "답변 초안": "bg-amber-100 text-amber-800", "담당자 연결": "bg-indigo-100 text-indigo-700",
  // 감정
  부정: "bg-rose-100 text-rose-700", 중립: "bg-slate-100 text-slate-600", 긍정: "bg-emerald-100 text-emerald-700",
  // 계정
  활성: "bg-emerald-100 text-emerald-700", 비활성: "bg-slate-200 text-slate-500", 잠김: "bg-rose-100 text-rose-700",
};

export function Badge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-xs text-slate-400">-</span>;
  return <span className={cx("inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", BADGE[value] ?? "bg-slate-100 text-slate-700")}>{value}</span>;
}

export function Spinner() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent align-[-2px]" aria-hidden />;
}

export function formatDate(iso: string | null | undefined) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
}
