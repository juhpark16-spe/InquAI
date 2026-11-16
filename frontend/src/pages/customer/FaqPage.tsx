// 자주 묻는 질문 (/faq): 유형별 탭, 검색. 답을 찾지 못하면 1:1 문의로 연결합니다.
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router";

import FaqItem from "../../components/FaqItem";
import { Alert, Card, Input, Spinner, cx } from "../../components/ui";
import { customerApi, errorMessage } from "../../services/api";
import { CATEGORIES, type FaqPublic } from "../../services/types";

export default function FaqPage() {
  const [params, setParams] = useSearchParams();
  const [faqs, setFaqs] = useState<FaqPublic[] | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const category = params.get("category") ?? "";
  const openCode = params.get("open");

  useEffect(() => {
    // 전체 탭에서도 유형끼리 모여 보이도록 유형 순서 → FAQ 번호 순으로 정렬
    const order = (c: string) => (CATEGORIES as readonly string[]).indexOf(c);
    customerApi.faqs()
      .then((list) => setFaqs([...list].sort((a, b) => order(a.category) - order(b.category) || a.code.localeCompare(b.code))))
      .catch((err) => setError(errorMessage(err)));
  }, []);

  // 추천에서 특정 FAQ로 들어오면 그 위치로 스크롤
  useEffect(() => {
    if (faqs && openCode) document.getElementById(openCode)?.scrollIntoView({ block: "center" });
  }, [faqs, openCode]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    faqs?.forEach((f) => { c[f.category] = (c[f.category] ?? 0) + 1; });
    return c;
  }, [faqs]);

  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const shown = (faqs ?? []).filter((f) =>
    (!category || f.category === category) &&
    words.every((w) => `${f.question} ${f.answer}`.toLowerCase().includes(w)));

  const tab = (value: string, label: string, count: number) => (
    <button key={value || "all"} onClick={() => setParams(value ? { category: value } : {})}
      className={cx("whitespace-nowrap rounded-full border px-3 py-1 text-sm",
        category === value ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 bg-white text-slate-600 hover:border-slate-400")}>
      {label} <span className={category === value ? "text-indigo-100" : "text-slate-400"}>{count}</span>
    </button>
  );

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-900">자주 묻는 질문</h1>
        <p className="text-sm text-slate-500">문의하시기 전에 먼저 확인해 보세요.</p>
      </div>

      <Input type="search" placeholder="궁금한 내용을 검색하세요 (예: 반품 배송비, 적립금)" value={q} onChange={(e) => setQ(e.target.value)} />

      <div className="flex flex-wrap gap-2">
        {tab("", "전체", faqs?.length ?? 0)}
        {CATEGORIES.filter((c) => counts[c]).map((c) => tab(c, c, counts[c]))}
      </div>

      {error && <Alert>{error}</Alert>}
      <Card>
        {!faqs && !error && <p className="py-6 text-center text-slate-500"><Spinner /></p>}
        {faqs && shown.length === 0 && <p className="py-6 text-center text-sm text-slate-500">검색 결과가 없습니다.</p>}
        {shown.map((f) => <FaqItem key={f.code} faq={f} open={f.code === openCode} />)}
      </Card>

      <div className="flex items-center justify-between rounded-xl border border-dashed border-slate-300 bg-white px-5 py-4 text-sm">
        <span className="text-slate-600">원하는 답을 찾지 못하셨나요?</span>
        <Link to="/inquiry" className="rounded-lg bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-700">1:1 문의하기</Link>
      </div>
    </div>
  );
}
