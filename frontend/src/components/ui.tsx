// 여러 화면이 같이 쓰는 작은 UI 조각
import type { ComponentProps, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export function cx(...names: (string | false | null | undefined)[]) {
  return names.filter(Boolean).join(" ");
}

const fieldBase =
  "min-h-11 rounded-xl border border-hairline bg-white px-4 py-2.5 text-sm text-ink outline-none placeholder:text-slate-400 focus:border-primary focus:ring-2 focus:ring-primary/15 disabled:bg-surface-card";
const inputBase = `w-full ${fieldBase}`;

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-sm font-semibold text-ink">{label}</span>
      {children}
      {hint && <span className="block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputBase, props.className)} />;
}

// ComponentProps<"textarea">: ref 도 받음 (React 19는 함수 컴포넌트에 ref 를 그대로 넘김, 답변 칸의 커서 자리에 넣기용)
export function Textarea(props: ComponentProps<"textarea">) {
  return <textarea {...props} className={cx(inputBase, "min-h-32", props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(fieldBase, props.className)} />;
}

export function Button({ variant = "primary", ...props }: ComponentProps<"button"> & { variant?: "primary" | "ghost" | "danger" }) {
  const styles = {
    // 기본 버튼 = 파란색, 보조 버튼 = 흰 바탕 + 테두리
    primary: "bg-primary text-white shadow-sm shadow-primary/20 hover:bg-primary-hover disabled:bg-hairline disabled:text-muted disabled:shadow-none",
    ghost: "border border-hairline bg-white text-ink hover:bg-surface-card disabled:text-slate-400",
    danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
  }[variant];
  return (
    <button {...props} className={cx("inline-flex min-h-11 items-center justify-center whitespace-nowrap rounded-xl px-5 py-2.5 text-sm font-semibold transition disabled:cursor-not-allowed", styles, props.className)} />
  );
}

export function Card({ title, children, className }: { title?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-2xl border border-hairline bg-white p-6", className)}>
      {title && <h2 className="mb-4 text-lg font-semibold text-ink">{title}</h2>}
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
  return <div role={kind === "error" ? "alert" : "status"} className={cx("rounded-xl border px-4 py-3 text-sm", styles)}>{children}</div>;
}

// 색의 뜻을 하나로 (2026-11-19): 빨강 = 급함·문제 · 초록 = 좋음 · 파랑 = 아직 할 일 · 회색 = 끝남·참고
// 색이 없는 값(보통·낮음·중립)은 배경 없이 글자만 → 목록에서 색 있는 배지가 곧 '봐야 할 것'
const PLAIN = "px-0! text-body";
const BADGE: Record<string, string> = {
  // 긴급도: 높음만 빨간 배지
  높음: "bg-rose-100 font-semibold text-rose-700", 보통: PLAIN, 낮음: "px-0! text-muted",
  // 상태: 미처리 = 파랑 계열, 끝남 = 회색
  접수: "bg-sky-100 text-sky-800", "검토 대기": "bg-primary-soft text-primary", "담당자 처리": "bg-indigo-100 text-indigo-800",
  "자동 처리": "bg-slate-100 text-slate-600", 완료: "bg-slate-100 text-slate-600",
  // 처리 방식: 좋고 나쁨이 없는 분류라 모두 회색
  "자동 답변": "bg-slate-100 text-slate-700", "답변 초안": "bg-slate-100 text-slate-700", "담당자 연결": "bg-slate-100 text-slate-700",
  // 감정: 부정만 빨강, 긍정은 초록
  부정: "bg-rose-100 text-rose-700", 중립: PLAIN, 긍정: "bg-emerald-100 text-emerald-700",
  // 계정
  활성: "bg-emerald-100 text-emerald-700", 비활성: "bg-slate-200 text-slate-500", 잠김: "bg-rose-100 text-rose-700",
};

export function Badge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-xs text-slate-400">-</span>;
  return <span className={cx("inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium", BADGE[value] ?? "bg-slate-100 text-slate-700")}>{value}</span>;
}

export function Spinner() {
  return <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent align-[-2px]" aria-hidden />;
}

/** 이름 첫 글자 (아바타용). "상담원 김하늘" → "김", "관리자" → "관" */
export function initialOf(name: string) {
  const rest = name.replace(/^(상담원|관리자)\s*/, "").trim();
  return (rest || name).slice(0, 1) || "?";
}

export function formatDate(iso: string | null | undefined) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
}
