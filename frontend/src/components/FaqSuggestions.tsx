// 문의 폼 추천: 제목·내용을 쓰는 동안 비슷한 FAQ를 보여 줍니다 (입력이 멈추고 0.6초 뒤 검색).
import { useEffect, useState } from "react";

import { customerApi } from "../services/api";
import type { FaqPublic } from "../services/types";
import FaqItem from "./FaqItem";

export default function FaqSuggestions({ text }: { text: string }) {
  const [items, setItems] = useState<FaqPublic[]>([]);

  useEffect(() => {
    const q = text.trim();
    if (q.length < 5) {
      setItems([]);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      customerApi.suggestFaqs(q, ctrl.signal).then(setItems).catch(() => { /* 추천은 실패해도 문의 등록과 무관 */ });
    }, 600);
    return () => { clearTimeout(timer); ctrl.abort(); };
  }, [text]);

  if (items.length === 0) return null;
  return (
    <div className="rounded-lg border border-sky-200 bg-sky-50/60 px-4 py-2">
      <p className="pt-1 text-sm font-medium text-sky-800">혹시 이 내용을 찾으시나요?</p>
      <div>{items.map((f) => <FaqItem key={f.code} faq={f} compact />)}</div>
      <p className="pb-1 text-xs text-slate-500">해결되지 않으면 그대로 문의를 등록해 주세요.</p>
    </div>
  );
}
