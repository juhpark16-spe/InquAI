// 문의 상세 (/admin/inquiries/:id) — 상담원이 처리하는 순서대로 배치
//   상단 고정: 무엇을·얼마나 급하게 (제목, 긴급도, 상태, 경과 시간) + 바로 할 수 있는 처리 (담당자, 완료/다시 열기)
//   왜 왔나: AI가 사람에게 넘긴 이유
//   왼쪽(일하는 곳): 고객 문의 → 답변(작성·승인은 3주차) → 처리 이력
//   오른쪽(판단 근거): 주문 정보(취소·반품 가능 여부) → 고객과 이전 문의 → AI 분석 → 티켓 → AI 처리 상세(점검용, 접힘)
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import AnalysisEditor from "../../components/AnalysisEditor";
import AnswerComposer from "../../components/AnswerComposer";
import { Alert, Badge, Button, Card, Select, Spinner, cx, formatDate } from "../../components/ui";
import { errorMessage, inquiryApi } from "../../services/api";
import type { AgentLog, InquiryDetail, OrderCard, User } from "../../services/types";

const OPEN = ["접수", "검토 대기", "담당자 처리"];
const LOW_CONFIDENCE = 0.8;
const FAQ_MIN_SCORE = 0.18; // backend/api/faqs_public.py SUGGEST_MIN_SCORE 와 같은 값

function timeAgo(iso: string) {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  if (min < 60 * 24) return `${Math.floor(min / 60)}시간 전`;
  return `${Math.floor(min / 1440)}일 전`;
}

function daysLeft(iso: string) {
  const d = Math.ceil((new Date(iso).getTime() - Date.now()) / 86400000);
  return d >= 0 ? `D-${d}` : `${-d}일 지남`;
}

const won = (n: number | null) => (n === null ? "-" : `${n.toLocaleString()}원`);

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-800">{children}</dd>
    </>
  );
}

function YesNo({ ok, yes, no }: { ok: boolean | null; yes: string; no: string }) {
  if (ok === null) return <span className="text-slate-400">-</span>;
  return <span className={ok ? "text-emerald-700" : "text-slate-500"}>{ok ? `✓ ${yes}` : `✕ ${no}`}</span>;
}

/** AI가 이 문의를 사람에게 넘긴 이유 (또는 자동 답변 완료) */
function DecisionBanner({ d }: { d: InquiryDetail }) {
  const a = d.analysis;
  if (!a) return <Alert kind="info">아직 AI 분석이 없습니다. 원문을 보고 직접 처리해 주세요.</Alert>;
  const log = d.agent_logs.at(-1);
  const style = a.decision === "자동 답변" ? "border-emerald-200 bg-emerald-50"
    : a.urgency === "높음" ? "border-rose-200 bg-rose-50" : "border-amber-200 bg-amber-50";
  const title = a.decision === "자동 답변" ? "AI가 FAQ를 근거로 자동 답변을 보냈습니다"
    : a.decision === "담당자 연결" ? "AI가 담당자에게 넘긴 문의입니다" : "AI가 상담원 검토가 필요하다고 판단했습니다";
  return (
    <div className={cx("rounded-xl border px-4 py-3", style)}>
      <p className="text-sm font-semibold text-slate-900">
        {a.urgency === "높음" && <span className="text-rose-700">⚠ 긴급 · </span>}{title}
        <span className="ml-2 text-xs font-normal text-slate-500">({a.decided_by} 판단 · 처리 경로 {a.route})</span>
      </p>
      {a.decision_reason && <p className="mt-1 text-sm text-slate-700">{a.decision_reason}</p>}
      {log?.error && <p className="mt-1 text-sm text-rose-700">AI 처리 중 오류가 있어 상담원에게 넘어왔습니다.</p>}
    </div>
  );
}

/** 주문 한 건의 상세: 상태·배송·취소·반품 가능 기한 */
function OrderRows({ o }: { o: OrderCard }) {
  return (
    <dl className="grid grid-cols-[5.5rem_1fr] gap-y-1.5 text-sm">
      <Row label="주문 상태"><Badge value={o.order_status} /></Row>
      <Row label="배송">{o.shipping_status ?? "-"}{o.tracking_number && <span className="ml-1 font-mono text-xs text-slate-500">({o.tracking_number})</span>}</Row>
      <Row label="주문일">{formatDate(o.ordered_at)}</Row>
      <Row label="배송 완료">{formatDate(o.delivered_at)}</Row>
      <Row label="취소"><YesNo ok={o.cancellable} yes="가능 (출고 전)" no="불가 (출고됨)" /></Row>
      <Row label="반품·교환">
        {o.return_until ? (
          <span>
            <YesNo ok={o.returnable} yes={`가능 ${daysLeft(o.return_until)}`} no="단순 변심 기한 지남" />
            {!o.returnable && o.defect_return_until && (
              <span className="block text-xs text-slate-500">불량·오배송은 {daysLeft(o.defect_return_until)}</span>
            )}
          </span>
        ) : <span className="text-slate-400">배송 완료 후 판단</span>}
      </Row>
    </dl>
  );
}

/** 주문 정보: 고객이 적은 주문(크게) + 문의 이메일로 찾은 다른 주문(접어서) */
function OrderInfo({ o, others }: { o: OrderCard | null; others: OrderCard[] }) {
  return (
    <Card title={<span>주문 정보 {o?.found && <span className="font-mono text-xs font-normal text-slate-500">{o.order_number}</span>}</span>}>
      {!o && <p className="text-sm text-slate-500">고객이 주문번호를 적지 않았습니다.</p>}
      {o && !o.found && (
        <Alert>주문번호 <b className="font-mono">{o.order_number}</b>를 찾을 수 없습니다. 고객에게 주문번호를 다시 확인해 주세요.</Alert>
      )}
      {o?.found && (
        <>
          {o.email_match === false && (
            <div className="mb-3"><Alert>문의 이메일과 주문자 이메일이 다릅니다 (주문자: {o.orderer}). 본인 확인 전에는 주문 정보를 안내하지 마세요.</Alert></div>
          )}
          <p className="mb-2 font-medium text-slate-900">{o.product_name} <span className="text-sm font-normal text-slate-500">{won(o.amount)}</span></p>
          <OrderRows o={o} />
        </>
      )}

      {others.length > 0 ? (
        <div className={cx(o?.found && "mt-4 border-t border-slate-100 pt-3")}>
          <p className="text-xs font-medium text-slate-500">{o?.found ? `이 고객의 다른 주문 (${others.length})` : `문의 이메일로 찾은 주문 (${others.length})`}</p>
          {!o?.found && (
            <p className="mt-1 rounded-md bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
              주문번호 없이 이메일로 찾은 주문입니다. 어떤 주문인지, 본인이 맞는지 고객에게 확인한 뒤 안내하세요.
            </p>
          )}
          <ul className="mt-2 space-y-1">
            {others.map((x) => (
              <li key={x.order_number}>
                <details className="group rounded-lg border border-slate-200">
                  <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm">
                    <span className="min-w-0 flex-1 truncate">{x.product_name}</span>
                    <Badge value={x.order_status} />
                    <span className="text-xs text-slate-400">{formatDate(x.ordered_at)}</span>
                  </summary>
                  <div className="border-t border-slate-100 px-3 py-2">
                    <p className="mb-1 font-mono text-xs text-slate-500">{x.order_number} · {won(x.amount)}</p>
                    <OrderRows o={x} />
                  </div>
                </details>
              </li>
            ))}
          </ul>
        </div>
      ) : !o?.found && (
        <p className="mt-1 text-xs text-slate-400">이 이메일로 된 주문도 없습니다.</p>
      )}
      <p className="mt-3 text-xs text-slate-400">기한은 쇼핑몰 정책 기준 (단순 변심 7일, 불량·오배송 30일)</p>
    </Card>
  );
}

function AiDetails({ log, faqTitles }: { log: AgentLog | undefined; faqTitles: Record<string, string> }) {
  if (!log) return null;
  return (
    <details className="group rounded-xl border border-slate-200 bg-white shadow-sm">
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-sm font-semibold text-slate-900">
        AI 처리 상세 <span className="text-xs font-normal text-slate-400">점검용 · 펼치기 <span className="inline-block transition group-open:rotate-180">⌄</span></span>
      </summary>
      <dl className="grid grid-cols-[6rem_1fr] gap-y-1.5 border-t border-slate-100 px-5 py-3 text-sm">
        {log.steps && log.steps.length > 0 && <Row label="처리 경로">{log.steps.join(" → ")}</Row>}
        {log.trace_url && (
          <Row label="추적">
            <a href={log.trace_url} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
              LangSmith에서 단계별로 보기 ↗
            </a>
          </Row>
        )}
        <Row label="사용한 도구">{log.selected_tool ?? "-"} {log.tool_success === false && <span className="text-rose-700">(실패)</span>}</Row>
        <Row label="검색된 FAQ">
          {log.retrieved_faqs.length ? (
            <ul className="space-y-0.5">
              {log.retrieved_faqs.map(([code, s]) => (
                <li key={code} className="text-xs"><span className="font-mono">{code}</span> {faqTitles[code] ?? ""} <span className="text-slate-400">유사도 {s.toFixed(2)}</span></li>
              ))}
            </ul>
          ) : "-"}
        </Row>
        <Row label="LLM">{log.llm_model ?? "사용 안 함 (규칙 판단)"}</Row>
        <Row label="토큰">{log.tokens?.calls ? `입력 ${log.tokens.input} · 출력 ${log.tokens.output} (${log.tokens.calls}회)` : "-"}</Row>
        <Row label="처리 시간">{log.latency_ms !== null ? `${(log.latency_ms / 1000).toFixed(1)}초` : "-"}</Row>
        {log.error && <Row label="오류"><span className="break-all text-rose-700">{log.error}</span></Row>}
        <Row label="도구 원본">
          {log.tool_output ? <pre className="overflow-x-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(log.tool_output, null, 2)}</pre> : "-"}
        </Row>
      </dl>
    </details>
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
  const isOpen = OPEN.includes(data.status);
  const lowConf = !!a && a.confidence < LOW_CONFIDENCE;
  const topScores = Object.entries(a?.scores?.category ?? {}).sort((x, y) => y[1] - x[1]).slice(0, 3);
  // 검색 점수가 낮은 FAQ는 관계없는 경우가 많아 참고 목록에서 뺌 (고객 화면 추천과 같은 기준)
  const refFaqs = (log?.retrieved_faqs ?? []).filter(([, s]) => s >= FAQ_MIN_SCORE);

  return (
    <div className="space-y-4">
      {/* 상단 고정: 무엇을, 얼마나 급하게 + 바로 할 수 있는 처리 */}
      <div className="sticky top-0 z-10 -mx-4 border-b border-slate-200 bg-canvas/95 px-4 py-3 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <Link to="/admin/inquiries" className="text-xs text-slate-500 hover:text-slate-900">← 문의 목록</Link>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-lg font-semibold text-slate-900">{data.title}</h1>
              {a?.urgency === "높음" && <span className="rounded-full bg-rose-600 px-2 py-0.5 text-xs font-semibold text-white">⚠ 긴급</span>}
              <Badge value={data.status} />
            </div>
            <p className="text-xs text-slate-500">
              <span className="font-mono">{data.inquiry_number}</span> · 접수 {timeAgo(data.created_at)} ({formatDate(data.created_at)})
              {data.overdue ? <span className="ml-2 font-semibold text-rose-700">⏰ 답변 기한 초과 ({formatDate(data.due_at)})</span>
                : isOpen && <span className="ml-2">· 답변 기한 {formatDate(data.due_at)}</span>}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-slate-500">담당</span>
            {user?.role === "admin" ? (
              <Select disabled={busy} value={data.assigned_to?.id ?? ""} aria-label="담당자"
                onChange={(e) => run(() => inquiryApi.assign(id, e.target.value ? Number(e.target.value) : null))}>
                <option value="">미배정</option>
                {staff.map((s) => <option key={s.id} value={s.id}>{s.display_name}</option>)}
              </Select>
            ) : (
              <span className="font-medium">{data.assigned_to?.display_name ?? "미배정"}</span>
            )}
            {isOpen ? (
              <Button disabled={busy} onClick={() => run(() => inquiryApi.setStatus(id, "완료"))}>완료 처리</Button>
            ) : (
              <Button variant="ghost" disabled={busy} onClick={() => run(() => inquiryApi.setStatus(id, "담당자 처리"))}>다시 열기</Button>
            )}
          </div>
        </div>
        {actionError && <div className="mt-2"><Alert>{actionError}</Alert></div>}
      </div>

      <DecisionBanner d={data} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        {/* 왼쪽: 일하는 곳 */}
        <div className="space-y-4">
          <Card title="대화">
            <AnswerComposer data={data} refFaqCodes={refFaqs.map(([code]) => code)} onChanged={load} />
          </Card>

          <details className="group rounded-xl border border-slate-200 bg-white shadow-sm">
            <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-sm font-semibold text-slate-900">
              전체 처리 이력 <span className="text-xs font-normal text-slate-400">초안 작성·수정까지 · 펼치기 <span className="inline-block transition group-open:rotate-180">⌄</span></span>
            </summary>
            <div className="border-t border-slate-100 px-5 py-4">
            <ol className="relative space-y-3 border-l border-slate-200 pl-4">
              {data.history.map((e, i) => (
                <li key={i} className="text-sm">
                  <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-slate-300" />
                  <span className="text-xs text-slate-500">{formatDate(e.at)} · {e.actor}</span>
                  <p className="text-slate-800">{e.text}</p>
                </li>
              ))}
            </ol>
            </div>
          </details>
        </div>

        {/* 오른쪽: 판단 근거 */}
        <div className="space-y-4">
          <OrderInfo o={data.order} others={data.email_orders} />

          <Card title="고객">
            <dl className="grid grid-cols-[4rem_1fr] gap-y-1 text-sm">
              <Row label="이름">{data.customer.name}</Row>
              <Row label="이메일"><span className="break-all">{data.customer.email}</span></Row>
            </dl>
            <p className="mb-1 mt-3 text-xs font-medium text-slate-500">이 고객의 다른 문의 {data.customer_history.length ? `(${data.customer_history.length})` : ""}</p>
            {data.customer_history.length === 0 ? <p className="text-sm text-slate-400">없음</p> : (
              <ul className="space-y-1 text-sm">
                {data.customer_history.map((h) => (
                  <li key={h.id} className="flex items-center justify-between gap-2">
                    <Link to={`/admin/inquiries/${h.id}`} className="truncate text-indigo-600 hover:underline">{h.title}</Link>
                    <span className="flex shrink-0 items-center gap-1 text-xs text-slate-400"><Badge value={h.status} />{timeAgo(h.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="AI 분석">
            {!a ? <p className="text-sm text-slate-500">분석 전</p> : (
              <>
                <dl className="grid grid-cols-[4rem_1fr] items-center gap-y-1.5 text-sm">
                  <Row label="유형">
                    {a.category} <span className={cx("text-xs", lowConf ? "font-semibold text-rose-700" : "text-slate-500")}>
                      확신도 {(a.confidence * 100).toFixed(0)}%{lowConf && " · 낮음, 유형 확인 필요"}
                    </span>
                  </Row>
                  <Row label="감정"><Badge value={a.sentiment} /></Row>
                  <Row label="긴급도"><Badge value={a.urgency} /></Row>
                </dl>
                <details className="mt-3" open={lowConf}>
                  <summary className="cursor-pointer text-xs text-slate-500">다른 유형 후보</summary>
                  <div className="mt-2 space-y-1">
                    {topScores.map(([label, p]) => (
                      <div key={label} className="flex items-center gap-2 text-xs">
                        <span className="w-24 truncate text-slate-600">{label}</span>
                        <div className="h-1.5 flex-1 rounded bg-slate-100"><div className="h-1.5 rounded bg-indigo-400" style={{ width: `${Math.round(p * 100)}%` }} /></div>
                        <span className="w-9 text-right tabular-nums text-slate-500">{(p * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-slate-400">모델 {a.model_version}</p>
                </details>
                <AnalysisEditor key={`${a.category}-${a.sentiment}`} data={data} onSaved={load} />
              </>
            )}
          </Card>

          {data.tickets.length > 0 && (
            <Card title="접수된 티켓">
              <ul className="space-y-1.5 text-sm">
                {data.tickets.map((t) => (
                  <li key={t.id} className="flex items-center justify-between">
                    <span>#{t.id} {t.ticket_type}</span><Badge value={t.status} />
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <AiDetails log={log} faqTitles={data.faq_titles} />
        </div>
      </div>
    </div>
  );
}
