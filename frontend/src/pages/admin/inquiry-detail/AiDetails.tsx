// 문의 상세 'AI 처리 상세' (관리자, 접힘): 처리 경로·판단 이유·검색된 FAQ·사용량
import { Row } from "../../../components/OrderParts";
import { TOOL_LABEL, byLabel, failReason, toolLabel } from "../../../services/labels";
import type { AgentLog } from "../../../services/types";

export function AiDetails({ log, faqTitles }: { log: AgentLog | undefined; faqTitles: Record<string, string> }) {
  if (!log) return null;
  return (
    <details className="group rounded-2xl border border-hairline bg-white">
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-lg font-semibold text-ink hover:bg-surface-soft">
        AI 처리 상세 <span className="text-sm font-normal text-slate-500">점검용 · 펼치기 <span className="inline-block transition group-open:rotate-180">⌄</span></span>
      </summary>
      <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1.5 border-t border-hairline px-5 py-3 text-sm">
        {log.steps && log.steps.length > 0 && <Row label="처리 경로">{log.steps.join(" → ")}</Row>}
        {log.trace_url && (
          <Row label="추적">
            <a href={log.trace_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
              LangSmith에서 단계별로 보기 ↗
            </a>
          </Row>
        )}
        <Row label="AI 처리 작업">
          <span title={log.selected_tool ? TOOL_LABEL[log.selected_tool]?.help : undefined}>{toolLabel(log.selected_tool)}</span>{" "}
          <span className="text-muted">({byLabel(log.decided_by)})</span>{" "}
          {log.tool_success === false && <span className="text-rose-700">· 미완료: {failReason(log.tool_output)}</span>}
        </Row>
        <Row label="검색된 FAQ">
          {log.retrieved_faqs.length ? (
            <ul className="space-y-0.5">
              {log.retrieved_faqs.map(([code, s]) => (
                <li key={code} className="text-sm"><span className="font-mono">{code}</span> {faqTitles[code] ?? ""} <span className="text-slate-500">유사도 {s.toFixed(2)}</span></li>
              ))}
            </ul>
          ) : "-"}
        </Row>
        <Row label="AI 모델">{log.llm_model ?? "사용 안 함 (규칙으로 바로)"}</Row>
        <Row label="AI 사용량">{log.tokens?.calls ? `입력 ${log.tokens.input} · 출력 ${log.tokens.output} (${log.tokens.calls}회)` : "-"}</Row>
        <Row label="처리 시간">{log.latency_ms !== null ? `${(log.latency_ms / 1000).toFixed(1)}초` : "-"}</Row>
        {log.error && <Row label="오류"><span className="break-all text-rose-700">{log.error}</span></Row>}
        <Row label="결과 원본">
          {log.tool_output ? <pre className="overflow-x-auto rounded bg-slate-50 p-2 text-sm">{JSON.stringify(log.tool_output, null, 2)}</pre> : "-"}
        </Row>
      </dl>
    </details>
  );
}
