// 문의 상세 화면에서 같이 쓰는 작은 부품: 경과 시간, 답변 기한, 카드·접는 구역, AI 판단 안내, 답변 칸에 문장 넣기
import { useEffect, useState, type ReactNode } from "react";
import { Alert, cx, formatDate } from "../../../components/ui";
import type { InquiryDetail } from "../../../services/types";

export const OPEN = ["접수", "검토 대기", "담당자 처리"];
export const LOW_CONFIDENCE = 0.8;
export const FAQ_MIN_SCORE = 0.18; // backend/api/faqs_public.py SUGGEST_MIN_SCORE 와 같은 값

export function timeAgo(iso: string) {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  if (min < 60 * 24) return `${Math.floor(min / 60)}시간 전`;
  return `${Math.floor(min / 1440)}일 전`;
}



/** 남은 답변 기한: 1시간 넘게 남으면 보통, 1시간 이내 주황, 지나면 빨강 (1분마다 다시 계산) */
export function DueTime({ due, overdue, open }: { due: string; overdue: boolean; open: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 60_000);
    return () => clearInterval(t);
  }, []);
  if (!open) return null;
  const left = new Date(due).getTime() - now;
  if (overdue || left <= 0) {
    return <span className="ml-2 rounded-full bg-rose-600 px-2 py-0.5 font-semibold text-white">⏰ 답변 기한 {Math.max(1, Math.round(-left / 3_600_000))}시간 지남</span>;
  }
  const mins = Math.round(left / 60_000);
  const label = mins < 60 ? `${mins}분 남음` : `${Math.floor(mins / 60)}시간 ${mins % 60 ? `${mins % 60}분 ` : ""}남음`;
  return (
    <span className={cx("ml-2 rounded-full px-2 py-0.5 font-medium", mins <= 60 ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600")}
      title={`답변 기한 ${formatDate(due)}`}>
      ⏱ 답변 기한 {label}
    </span>
  );
}

/** 상세 화면 카드: 흰 바탕 + 연한 테두리, 제목 줄 아래 얇은 선 (구역은 구분되되 상자가 내용보다 튀지 않게) */
export function Card({ title, action, children }: { title: ReactNode; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-hairline bg-white">
      <div className="flex items-center justify-between gap-3 border-b border-hairline px-5 py-3">
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        {action}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

/** 접을 수 있는 카드: 접힌 상태를 브라우저에 기억 (덜 보는 카드는 접어 두고 스크롤을 줄임) */
export function Fold({ id, title, summary, children, defaultOpen = true }: {
  id: string; title: string; summary?: ReactNode; children: ReactNode; defaultOpen?: boolean;
}) {
  const key = `inquai.fold.${id}`;
  const [open, setOpen] = useState(() => {
    try {
      const v = localStorage.getItem(key);
      return v === null ? defaultOpen : v === "1";
    } catch {
      return defaultOpen;
    }
  });
  const toggle = () => {
    setOpen(!open);
    try { localStorage.setItem(key, open ? "0" : "1"); } catch { /* 저장 못 해도 동작 */ }
  };
  return (
    <section className="overflow-hidden rounded-2xl border border-hairline bg-white">
      <button type="button" onClick={toggle} aria-expanded={open}
        className={cx("flex w-full items-center justify-between gap-3 px-5 py-3 text-left hover:bg-surface-soft", open && "border-b border-hairline")}>
        <span className="shrink-0 whitespace-nowrap text-lg font-semibold text-ink">{title}</span>
        <span className="flex min-w-0 items-center gap-2 text-sm text-muted">
          {!open && summary && <span className="truncate text-body">{summary}</span>}
          <span className="shrink-0">{open ? "접기 ▴" : "펼치기 ▾"}</span>
        </span>
      </button>
      {open && <div className="px-5 py-4">{children}</div>}
    </section>
  );
}


/** AI가 이 문의를 사람에게 넘긴 이유 (또는 자동 답변 완료) */
export function DecisionBanner({ d }: { d: InquiryDetail }) {
  const a = d.analysis;
  if (!a) return <Alert kind="info">아직 AI 분석이 없습니다. 원문을 보고 직접 처리해 주세요.</Alert>;
  const log = d.agent_logs.at(-1);
  const style = a.decision === "자동 답변" ? "border-l-emerald-500"
    : a.urgency === "높음" ? "border-l-rose-500" : "border-l-amber-500";
  const title = a.decision === "자동 답변" ? "AI가 FAQ를 근거로 자동 답변을 보냈습니다"
    : a.decision === "담당자 연결" ? "AI가 담당자에게 넘긴 문의입니다" : "AI가 상담원 검토가 필요하다고 판단했습니다";
  // 긴급 표시는 제목 옆에 이미 있고, 판단 방식·처리 경로는 'AI 처리 상세'(관리자)에서 봄 → 여기서는 이유 한 줄만
  const reason = a.decision_reason?.replace(/\s*\((규칙|LLM)\)\s*$/, "");
  return (
    <div className={cx("rounded-xl border border-l-4 border-hairline bg-white px-4 py-2.5 text-sm", style)}>
      <span className="font-semibold text-ink">{title}</span>
      {reason && <span className="text-body"> · {reason}</span>}
      {log?.error && <span className="text-rose-700"> · AI 처리 중 오류가 있어 상담원에게 넘어왔습니다</span>}
    </div>
  );
}


/** 답변 칸에 문장 넣기 (주문 정보 카드의 버튼 → AnswerComposer 가 받아 커서 자리에 넣음) */
export function insertIntoReply(text: string) {
  window.dispatchEvent(new CustomEvent("inquai:insert-reply", { detail: text }));
}
