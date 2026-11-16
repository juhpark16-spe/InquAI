// FAQ 한 개: 질문을 누르면 답변이 펼쳐짐 (FAQ 화면과 문의 폼의 추천에서 같이 씀)
import type { FaqPublic } from "../services/types";

export default function FaqItem({ faq, open, compact }: { faq: FaqPublic; open?: boolean; compact?: boolean }) {
  return (
    <details open={open} id={faq.code} className="group border-b border-slate-100 last:border-b-0">
      <summary className={`flex cursor-pointer list-none items-start gap-3 ${compact ? "py-2" : "py-3"} hover:text-indigo-700`}>
        <span className="mt-0.5 font-semibold text-indigo-600">Q</span>
        <span className="flex-1 text-sm font-medium">{faq.question}</span>
        <span className="whitespace-nowrap text-xs text-slate-400">{faq.category}</span>
        <span className="text-slate-400 transition group-open:rotate-180" aria-hidden>⌄</span>
      </summary>
      <div className="mb-3 flex gap-3 rounded-lg bg-slate-50 p-3">
        <span className="font-semibold text-emerald-600">A</span>
        <p className="flex-1 text-sm leading-relaxed text-slate-700">{faq.answer}</p>
      </div>
    </details>
  );
}
