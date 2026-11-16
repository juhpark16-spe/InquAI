// 문의 상세 (/admin/inquiries/:id): 원문, 분석 결과, 처리 방식과 판단 이유, 답변, 티켓, AI 실행 기록, 배정·상태 변경
// 답변 초안 편집·승인, 분류 수정은 3주차에 붙입니다.
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import { Alert, Badge, Button, Card, Select, Spinner, formatDate } from "../../components/ui";
import { errorMessage, inquiryApi } from "../../services/api";
import { MANUAL_STATUSES, type InquiryDetail, type User } from "../../services/types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-800">{children}</dd>
    </>
  );
}

function ScoreBars({ scores }: { scores?: Record<string, number> }) {
  if (!scores) return null;
  const top = Object.entries(scores).sort((a, b) => b[1] - a[1]).slice(0, 3);
  return (
    <div className="mt-2 space-y-1">
      {top.map(([label, p]) => (
        <div key={label} className="flex items-center gap-2 text-xs">
          <span className="w-28 truncate text-slate-600">{label}</span>
          <div className="h-1.5 flex-1 rounded bg-slate-100">
            <div className="h-1.5 rounded bg-indigo-400" style={{ width: `${Math.round(p * 100)}%` }} />
          </div>
          <span className="w-10 text-right tabular-nums text-slate-500">{(p * 100).toFixed(0)}%</span>
        </div>
      ))}
    </div>
  );
}

export default function InquiryDetailPage() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const [data, setData] = useState<InquiryDetail | null>(null);
  const [staff, setStaff] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    inquiryApi.get(id).then(setData).catch((err) => setError(errorMessage(err)));
  }, [id]);

  useEffect(load, [load]);
  useEffect(() => {
    if (user?.role === "admin") inquiryApi.staff().then(setStaff).catch(() => setStaff([]));
  }, [user]);

  async function run(action: () => Promise<unknown>) {
    setActionError("");
    setBusy(true);
    try {
      await action();
      load();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (error) return <Alert>{error}</Alert>;
  if (!data) return <p className="p-6 text-center text-slate-500"><Spinner /></p>;

  const a = data.analysis;
  const log = data.agent_logs.at(-1);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link to="/admin/inquiries" className="text-sm text-slate-500 hover:text-slate-900">← 목록</Link>
        <h1 className="text-lg font-semibold text-slate-900">{data.title}</h1>
        <Badge value={data.status} />
        <span className="font-mono text-xs text-slate-500">{data.inquiry_number}</span>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-4">
          <Card title="문의 원문">
            <p className="mb-3 whitespace-pre-line text-sm leading-relaxed">{data.content}</p>
            <dl className="grid grid-cols-[5rem_1fr] gap-y-1 border-t border-slate-100 pt-3 text-sm">
              <Row label="고객">{data.customer.name} · {data.customer.email}</Row>
              <Row label="주문번호">{data.customer.order_number ?? "-"}</Row>
              <Row label="접수">{formatDate(data.created_at)}</Row>
            </dl>
          </Card>

          <Card title="답변">
            {data.responses.length === 0 ? (
              <p className="text-sm text-slate-500">
                {a?.decision === "답변 초안" ? "AI 답변 초안 작성은 3주차에 연결합니다. 아래 도구 실행 결과를 참고해 주세요." : "아직 답변이 없습니다."}
              </p>
            ) : (
              <div className="space-y-3">
                {data.responses.map((r) => (
                  <div key={r.id} className="rounded-lg border border-slate-200 p-3">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <Badge value={r.status === "발송" ? "자동 답변" : "답변 초안"} />
                      <span>{r.status}{r.approved_at && ` · ${formatDate(r.approved_at)}`}</span>
                      <span>근거 FAQ: {r.used_faq_ids.length ? r.used_faq_ids.join(", ") : "없음"}</span>
                      {r.grounded === false && <span className="text-amber-700">FAQ 근거 부족으로 초안 전환</span>}
                    </div>
                    <p className="whitespace-pre-line text-sm leading-relaxed">{r.final_text ?? r.draft_text}</p>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title="AI 실행 기록">
            {!log ? (
              <p className="text-sm text-slate-500">실행 기록이 없습니다.</p>
            ) : (
              <dl className="grid grid-cols-[7rem_1fr] gap-y-1.5 text-sm">
                <Row label="선택한 도구">
                  {log.selected_tool ?? "-"}{" "}
                  {log.tool_success !== null && (
                    <span className={log.tool_success ? "text-emerald-700" : "text-rose-700"}>({log.tool_success ? "성공" : "실패"})</span>
                  )}
                </Row>
                <Row label="도구 결과">
                  {log.tool_output ? (
                    <pre className="overflow-x-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(log.tool_output, null, 2)}</pre>
                  ) : "-"}
                </Row>
                <Row label="검색된 FAQ">
                  {log.retrieved_faqs.length ? log.retrieved_faqs.map(([code, s]) => `${code} (${s.toFixed(2)})`).join(", ") : "-"}
                </Row>
                <Row label="LLM">{log.llm_model ?? "사용 안 함 (규칙 판단)"}</Row>
                <Row label="토큰">{log.tokens?.calls ? `입력 ${log.tokens.input} · 출력 ${log.tokens.output} (${log.tokens.calls}회)` : "-"}</Row>
                <Row label="처리 시간">{log.latency_ms !== null ? `${(log.latency_ms / 1000).toFixed(1)}초` : "-"}</Row>
                {log.error && <Row label="오류"><span className="text-rose-700">{log.error}</span></Row>}
              </dl>
            )}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="분석 결과">
            {!a ? (
              <p className="text-sm text-slate-500">아직 분석되지 않았습니다.</p>
            ) : (
              <div className="space-y-4 text-sm">
                <dl className="grid grid-cols-[5rem_1fr] items-center gap-y-1.5">
                  <Row label="유형">{a.category} <span className="text-slate-500">(확신도 {(a.confidence * 100).toFixed(0)}%)</span></Row>
                  <Row label="감정"><Badge value={a.sentiment} /></Row>
                  <Row label="긴급도"><Badge value={a.urgency} /></Row>
                  <Row label="처리 경로">{a.route}</Row>
                  <Row label="처리 방식"><Badge value={a.decision} /> <span className="text-xs text-slate-500">({a.decided_by})</span></Row>
                </dl>
                {a.decision_reason && (
                  <div>
                    <p className="mb-1 text-xs font-medium text-slate-500">판단 이유</p>
                    <p className="rounded-lg bg-slate-50 p-3 text-sm leading-relaxed">{a.decision_reason}</p>
                  </div>
                )}
                <div>
                  <p className="text-xs font-medium text-slate-500">유형 확률 (상위 3개)</p>
                  <ScoreBars scores={a.scores?.category} />
                </div>
                <p className="text-xs text-slate-400">모델 {a.model_version}</p>
              </div>
            )}
          </Card>

          <Card title="담당·상태">
            <div className="space-y-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">담당자</span>
                {user?.role === "admin" ? (
                  <Select disabled={busy} value={data.assigned_to?.id ?? ""}
                    onChange={(e) => run(() => inquiryApi.assign(id, e.target.value ? Number(e.target.value) : null))}>
                    <option value="">미배정</option>
                    {staff.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
                  </Select>
                ) : (
                  <span>{data.assigned_to?.display_name ?? "미배정"}</span>
                )}
              </div>
              <div className="flex items-center justify-between gap-2">
                <span className="text-slate-500">상태</span>
                <Select disabled={busy} value={MANUAL_STATUSES.includes(data.status as never) ? data.status : ""}
                  onChange={(e) => e.target.value && run(() => inquiryApi.setStatus(id, e.target.value))}>
                  {!MANUAL_STATUSES.includes(data.status as never) && <option value="">{data.status}</option>}
                  {MANUAL_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </Select>
              </div>
              {data.status !== "완료" && (
                <Button variant="ghost" className="w-full" disabled={busy} onClick={() => run(() => inquiryApi.setStatus(id, "완료"))}>
                  답변 없이 완료 처리
                </Button>
              )}
              {actionError && <Alert>{actionError}</Alert>}
            </div>
          </Card>

          <Card title={`티켓 (${data.tickets.length})`}>
            {data.tickets.length === 0 ? (
              <p className="text-sm text-slate-500">없음</p>
            ) : (
              <ul className="space-y-2 text-sm">
                {data.tickets.map((t) => (
                  <li key={t.id} className="flex items-center justify-between gap-2">
                    <span>#{t.id} {t.ticket_type}</span>
                    <span className="text-slate-500">{t.status}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
