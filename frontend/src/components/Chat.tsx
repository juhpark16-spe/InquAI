// 대화형(채팅) 화면 조각: 말풍선과 가운데 안내 줄
// 관리자 화면: 고객 = 왼쪽, AI·상담원 = 오른쪽 / 고객 화면: 나(고객) = 오른쪽, 고객센터 = 왼쪽
import type { ReactNode } from "react";

import { cx, formatDate } from "./ui";

export type Tone = "customer" | "ai" | "agent" | "memo";

const TONE: Record<Tone, { bubble: string; name: string; avatar: string; icon: string }> = {
  customer: { bubble: "bg-white border border-slate-200 text-slate-900", name: "text-slate-600", avatar: "bg-slate-200 text-slate-600", icon: "고" },
  ai: { bubble: "bg-emerald-50 border border-emerald-200 text-slate-900", name: "text-emerald-700", avatar: "bg-emerald-600 text-white", icon: "AI" },
  agent: { bubble: "bg-indigo-600 text-white", name: "text-indigo-700", avatar: "bg-indigo-100 text-indigo-700", icon: "상" },
  memo: { bubble: "bg-amber-50 border border-dashed border-amber-400 text-amber-950", name: "text-amber-700", avatar: "bg-amber-200 text-amber-800", icon: "메" },
};

export function Bubble({ side, tone, name, at, children, footer }: {
  side: "left" | "right";
  tone: Tone;
  name: string;
  at: string | null;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const t = TONE[tone];
  const right = side === "right";
  return (
    <div className={cx("flex items-end gap-2", right && "flex-row-reverse")}>
      <span className={cx("flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold", t.avatar)} aria-hidden>
        {t.icon}
      </span>
      <div className={cx("flex max-w-[80%] flex-col", right ? "items-end" : "items-start")}>
        <span className={cx("mb-1 text-xs font-medium", t.name)}>
          {name} <span className="font-normal text-slate-400">{formatDate(at)}</span>
        </span>
        <div className={cx("whitespace-pre-line rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed shadow-sm",
          t.bubble, right ? "rounded-br-md" : "rounded-bl-md")}>
          {children}
        </div>
        {footer && <div className="mt-1 text-xs text-slate-500">{footer}</div>}
      </div>
    </div>
  );
}

/** 말풍선 아래 작은 사진 (누르면 새 창에서 크게) */
export function Thumbs({ photos }: { photos: { url: string; filename: string }[] }) {
  if (!photos.length) return null;
  return (
    <span className="mt-1 flex flex-wrap justify-end gap-1.5">
      {photos.map((p) => (
        <a key={p.url} href={p.url} target="_blank" rel="noreferrer" title={`${p.filename} · 크게 보기`}>
          <img src={p.url} alt={p.filename} className="h-16 w-16 rounded-lg border border-slate-200 object-cover hover:opacity-90" />
        </a>
      ))}
    </span>
  );
}

/** 대화 사이의 안내 줄 (AI 판단, 배정, 상태 변경 등) */
export function Note({ children, tone = "plain" }: { children: ReactNode; tone?: "plain" | "warn" }) {
  return (
    <div className="flex items-center gap-3 py-1 text-xs">
      <span className="h-px flex-1 bg-slate-200" />
      <span className={cx("max-w-[80%] text-center", tone === "warn" ? "text-rose-700" : "text-slate-500")}>{children}</span>
      <span className="h-px flex-1 bg-slate-200" />
    </div>
  );
}
