// 입력이 있는 작은 창 (종료 사유 고르기, 문의 넘기기 등). 모양은 확인창(ConfirmDialog)과 같음
// - Esc·바깥 누르기 = 닫기. 관리 화면 판의 흐림 효과 안에서는 화면 전체를 덮지 못해 body 에 띄움
import { useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";

export default function Modal({ title, children, onClose, footer }: {
  title: string; children: ReactNode; onClose: () => void; footer: ReactNode;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-[2px]"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={title} className="w-full max-w-md rounded-2xl border border-hairline bg-white p-6 shadow-xl">
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        <div className="mt-3 space-y-3 text-sm text-body">{children}</div>
        <div className="mt-6 flex justify-end gap-2">{footer}</div>
      </div>
    </div>,
    document.body,
  );
}
