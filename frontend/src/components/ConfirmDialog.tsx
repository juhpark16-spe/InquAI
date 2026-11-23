// 확인창: 브라우저 기본 확인창(window.confirm) 대신 화면 디자인에 맞춘 창
//   if (!(await confirmDialog({ title: "FAQ 비활성화", message: "…", confirmLabel: "비활성화", tone: "danger" }))) return;
// - App 에 <ConfirmHost /> 한 번만 두고, 어디서든 confirmDialog() 를 부르면 창이 뜨고 [확인]이면 true
// - Esc·바깥 누르기·[취소] = false, Enter = 확인. 열리면 확인 버튼에 초점 (키보드로 바로 처리)
import { useEffect, useRef, useState } from "react";

import { Button } from "./ui";

export interface ConfirmOptions {
  title: string;
  message?: string;
  confirmLabel?: string;   // 기본 '확인'
  cancelLabel?: string;    // 기본 '취소'
  tone?: "primary" | "danger";   // danger: 되돌리기 어려운 일 (빨간 버튼)
}

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };
let open: ((p: Pending) => void) | null = null;

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    if (!open) {   // 창을 띄울 곳이 없으면(테스트 등) 기본 확인창으로
      resolve(window.confirm([options.title, options.message].filter(Boolean).join("\n\n")));
      return;
    }
    open({ ...options, resolve });
  });
}

export default function ConfirmHost() {
  const [pending, setPending] = useState<Pending | null>(null);
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    open = (p) => setPending((prev) => {
      prev?.resolve(false);   // 이전 창이 남아 있으면 취소로 닫음
      return p;
    });
    return () => { open = null; };
  }, []);

  useEffect(() => {
    if (!pending) return;
    okRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  function close(ok: boolean) {
    pending?.resolve(ok);
    setPending(null);
  }

  if (!pending) return null;
  const danger = pending.tone === "danger";
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) close(false); }}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message"
        className="w-full max-w-md rounded-2xl border border-hairline bg-white p-6 shadow-xl">
        <div className="flex items-start gap-3">
          <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-lg ${danger ? "bg-rose-50 text-rose-600" : "bg-primary-soft text-primary"}`}
            aria-hidden>{danger ? "!" : "?"}</span>
          <div className="min-w-0 pt-1">
            <h2 id="confirm-title" className="text-lg font-semibold text-ink">{pending.title}</h2>
            {pending.message && <p id="confirm-message" className="mt-1.5 whitespace-pre-line text-sm leading-relaxed text-body">{pending.message}</p>}
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => close(false)}>{pending.cancelLabel ?? "취소"}</Button>
          <Button ref={okRef} variant={danger ? "danger" : "primary"} onClick={() => close(true)}>{pending.confirmLabel ?? "확인"}</Button>
        </div>
      </div>
    </div>
  );
}
