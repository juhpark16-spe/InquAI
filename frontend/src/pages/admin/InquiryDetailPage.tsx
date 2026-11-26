// 문의 상세 (/admin/inquiries/:id) — 상담원이 처리하는 순서대로 배치
//   상단 고정: 무엇을·얼마나 급하게 (제목, 긴급도, 상태, 경과 시간) + 바로 할 수 있는 처리 (담당자, 완료/다시 열기)
//   왜 왔나: AI가 사람에게 넘긴 이유
//   왼쪽(일하는 곳): 고객 문의 → 답변(작성·승인은 3주차) → 처리 이력
//   오른쪽(판단 근거, 25rem 고정 폭 → 일하는 곳이 넓게): 처리할 티켓 → 주문 정보(취소·반품 가능 여부) → 고객(누구인지·불만 신호)
//     → AI 분석 → 처리된 티켓 → AI 처리 상세(관리자, 접힘). 주문과 관계없는 문의(쿠폰·회원 등)는 고객을 먼저
//   카드는 흰 바탕 + 연한 테두리로 가볍게. 글씨: 구역 제목 17 · 왼쪽 본문 15 · 오른쪽 참고 정보 14px
// 파일: 이 파일은 화면 배치·불러오기·상단 처리만. 카드는 inquiry-detail/ 폴더에 역할별로
//   Tickets(취소·교환·반품 요청) · OrderInfo(주문 정보) · OrderActions(바로 처리·보상) · Dialogs(완료·넘기기 창)
//   · AiDetails(AI 처리 상세) · parts(카드·접는 구역·기한 등 작은 부품)
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { useAuth } from "../../auth/AuthProvider";
import AnalysisEditor from "../../components/AnalysisEditor";
import AnswerComposer from "../../components/AnswerComposer";
import InternalNotes from "../../components/InternalNotes";
import { confirmDialog } from "../../components/ConfirmDialog";
import { Row, SubFold } from "../../components/OrderParts";
import { Alert, Badge, Button, Select, Spinner, cx, formatDate } from "../../components/ui";
import { errorMessage, inquiryApi } from "../../services/api";
import type { InquiryDetail, User } from "../../services/types";
import { staffLabel } from "../../services/types";
import { Card, DecisionBanner, DueTime, FAQ_MIN_SCORE, Fold, LOW_CONFIDENCE, OPEN, timeAgo } from "./inquiry-detail/parts";
import { ORDER_CATEGORIES, OrderInfo } from "./inquiry-detail/OrderInfo";
import { CustomerActions } from "./inquiry-detail/OrderActions";
import { CloseDialog, HandoverDialog } from "./inquiry-detail/Dialogs";
import { TICKET_ACTIONABLE, Tickets } from "./inquiry-detail/Tickets";
import { AiDetails } from "./inquiry-detail/AiDetails";

export default function InquiryDetailPage() {
  const id = Number(useParams().id);
  const { user } = useAuth();
  const [data, setData] = useState<InquiryDetail | null>(null);
  const [staff, setStaff] = useState<User[]>([]);
  const [dialog, setDialog] = useState<"close" | "handover" | null>(null);
  // 쓰던 답변이 있으면 다른 문의로 옮기기 전에 물음 (옮기면 답변 칸이 비워짐)
  const dirty = useRef(false);
  async function go(to: number | null | undefined) {
    if (!to) return;
    if (dirty.current && !(await confirmDialog({
      title: "작성 중인 답변이 있어요", message: "다른 문의로 옮기면 쓰던 답변이 사라져요.\n남기려면 [초안 저장]을 먼저 눌러 주세요.",
      confirmLabel: "옮기기", cancelLabel: "머무르기", tone: "danger",
    }))) return;
    dirty.current = false;
    navigate(`/admin/inquiries/${to}`);
  }
  // 새로 고침·창 닫기도 브라우저가 한 번 물음
  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => { if (dirty.current) e.preventDefault(); };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, []);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [queue, setQueue] = useState<{ total: number; position: number | null; prev_id: number | null; next_id: number | null } | null>(null);
  const navigate = useNavigate();
  // 화면 안의 다른 링크(문의 목록·고객 정보·왼쪽 메뉴 등)를 눌러도 쓰던 답변이 있으면 먼저 물음 (◀▶ 버튼과 같은 확인)
  useEffect(() => {
    const onClick = async (e: MouseEvent) => {
      if (!dirty.current || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
      const a = (e.target as HTMLElement).closest("a[href]") as HTMLAnchorElement | null;
      if (!a || a.target === "_blank" || a.origin !== window.location.origin || a.pathname === window.location.pathname) return;
      e.preventDefault();
      e.stopPropagation();
      if (!(await confirmDialog({
        title: "작성 중인 답변이 있어요", message: "다른 화면으로 옮기면 쓰던 답변이 사라져요.\n남기려면 [초안 저장]을 먼저 눌러 주세요.",
        confirmLabel: "옮기기", cancelLabel: "머무르기", tone: "danger",
      }))) return;
      dirty.current = false;
      navigate(a.pathname + a.search);
    };
    document.addEventListener("click", onClick, true);   // 링크(React Router)보다 먼저 받음
    return () => document.removeEventListener("click", onClick, true);
  }, [navigate]);

  // 지금 보고 있는 문의 번호: 늦게 도착한 다른 문의의 응답(예: 발송 5초 뒤 다시 불러오기)이 화면을 덮지 않게
  const currentId = useRef(id);
  currentId.current = id;
  const load = useCallback(() => {
    inquiryApi.get(id)
      .then((d) => { if (currentId.current === id) setData(d); })
      .catch((err) => { if (currentId.current === id) setError(errorMessage(err)); });
  }, [id]);
  useEffect(load, [load]);
  // 다른 문의로 옮기면 안내 문구를 지움
  useEffect(() => { setNotice(""); setActionError(""); }, [id]);
  // 단축키 Alt+← / Alt+→ : 이전·다음 미처리 문의
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || !queue) return;
      const to = e.key === "ArrowLeft" ? queue.prev_id : e.key === "ArrowRight" ? queue.next_id : null;
      if (to) { e.preventDefault(); go(to); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queue, navigate]); // eslint-disable-line react-hooks/exhaustive-deps -- go 는 ref(dirty)와 navigate 만 써서 매번 새로 받을 필요 없음
  // 처리 대기열 위치: 상태가 바뀔 때마다 다시 (완료하면 대기열에서 빠지고 '다음 미처리'가 바뀜)
  useEffect(() => {
    inquiryApi.queue(id).then(setQueue).catch(() => setQueue(null));
  }, [id, data?.status]);
  useEffect(() => {
    inquiryApi.staff().then(setStaff).catch(() => setStaff([]));   // 관리자: 배정, 상담원: 넘길 상대
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
  if (!data) return <p className="p-6 text-center text-slate-600"><Spinner /></p>;

  const a = data.analysis;
  const log = data.agent_logs.at(-1);
  const isOpen = OPEN.includes(data.status);
  const lowConf = !!a && a.confidence < LOW_CONFIDENCE;
  const recheck = a?.scores?.page_recheck;   // 상품 페이지 표기 오류 신호가 있을 때 AI가 유형을 다시 본 결과
  const topScores = Object.entries(a?.scores?.category ?? {}).sort((x, y) => y[1] - x[1]).slice(0, 3);
  // 검색 점수가 낮은 FAQ는 관계없는 경우가 많아 참고 목록에서 뺌 (고객 화면 추천과 같은 기준)
  const refFaqs = (log?.retrieved_faqs ?? []).filter(([, s]) => s >= FAQ_MIN_SCORE);
  const p = data.customer_profile;
  const warn = !!p && (p.negative_ratings > 0 || p.negative_inquiries >= 2);
  const hasRequests = data.tickets.some((t) => TICKET_ACTIONABLE.includes(t.ticket_type));   // 취소·교환·반품 요청 (이관 제외)

  // 고객 카드: 누구인지·불만 신호·이 고객의 다른 문의 (다른 문의는 3건까지 보이고 나머지는 접음)
  const history = data.customer_history;
  const historyRow = (h: (typeof history)[number]) => (
    <li key={h.id} className="flex items-center justify-between gap-2">
      <Link to={`/admin/inquiries/${h.id}`} className="truncate text-primary hover:underline">{h.title}</Link>
      <span className="flex shrink-0 items-center gap-1.5 text-xs text-muted"><Badge value={h.status} />{timeAgo(h.created_at)}</span>
    </li>
  );
  const actionDone = (m: string) => { setNotice(m); load(); };   // 바로 처리 결과 → 위쪽 안내 + 다시 불러오기
  const customerCard = (
    <Fold id="customer" title="고객" summary={`${data.customer.name}${p ? ` · 문의 ${p.inquiries}건` : ""}${warn ? " · ⚠ 불만 신호" : ""}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-base font-semibold text-ink">{data.customer.name}</span>
        <span className={cx("rounded-full px-2 py-0.5 text-xs font-medium", p?.member ? "bg-primary-soft text-primary" : "bg-slate-100 text-slate-600")}>
          {p?.member ? "쇼핑몰 회원" : "비회원 문의"}
        </span>
        {p?.customer_id && (
          <Link to={`/admin/customers/${p.customer_id}`} className="ml-auto text-xs font-semibold text-primary hover:underline">고객 정보 전체 보기 →</Link>
        )}
      </div>
      <dl className="mt-2 grid grid-cols-[3.5rem_1fr] gap-x-3 gap-y-1 text-sm">
        <Row label="이메일"><span className="break-all">{data.customer.email}</span></Row>
        {p?.phone && <Row label="전화">{p.phone}</Row>}
        {p && <Row label="이력">주문 {p.orders}건 · 문의 {p.inquiries}건</Row>}
        {p?.points_balance != null && (
          <Row label="적립금">
            <span className="font-semibold">{p.points_balance.toLocaleString()}원</span>
            {p.points_pending > 0 && <span className="text-muted"> · 적립 예정 {p.points_pending.toLocaleString()}원</span>}
            {p.coupons.length > 0 && <span className="text-muted"> · 쿠폰 {p.coupons.filter((c) => c.state === "사용 가능").length}장</span>}
          </Row>
        )}
      </dl>
      {p && (p.point_history.length > 0 || p.coupons.length > 0) && (
        <SubFold title="적립금·쿠폰 내역" open={a?.category === "쿠폰·적립금·회원"}>
          {p.point_history.length > 0 && (
            <ul className="space-y-1 text-sm">
              {p.point_history.map((h, i) => (
                <li key={i} className="flex items-baseline justify-between gap-2">
                  <span className="min-w-0 truncate">{h.reason}{h.status === "예정" && <span className="text-amber-700"> (예정)</span>}
                    <span className="text-xs text-muted"> · {formatDate(h.at)}</span></span>
                  <span className={cx("shrink-0 font-semibold tabular-nums", h.amount < 0 ? "text-rose-700" : "text-emerald-700")}>
                    {h.amount > 0 ? "+" : ""}{h.amount.toLocaleString()}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {p.coupons.length > 0 && (
            <ul className="mt-2.5 space-y-1 border-t border-hairline pt-2 text-sm">
              {p.coupons.map((c, i) => (
                <li key={i} className={cx("flex items-baseline justify-between gap-2", c.state !== "사용 가능" && "text-muted")}>
                  <span className="min-w-0 truncate">{c.name} <span className="text-xs">· {c.benefit}{c.min_amount ? ` · ${c.min_amount.toLocaleString()}원 이상` : ""}</span></span>
                  <span className={cx("shrink-0 text-xs", c.state === "사용 가능" && "font-semibold text-primary")}>
                    {c.state}{c.state === "사용 가능" && ` · ~${formatDate(c.expires_at).split(" ").slice(0, 3).join(" ")}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </SubFold>
      )}
      {warn && (
        <p className="mt-2 rounded-lg bg-amber-50 px-3 py-1.5 text-sm text-amber-900">
          ⚠ 응대에 신경 쓸 고객:
          {p!.negative_ratings > 0 && <> 이전 답변에 👎 {p!.negative_ratings}번</>}
          {p!.negative_ratings > 0 && p!.negative_inquiries >= 2 && " ·"}
          {p!.negative_inquiries >= 2 && <> 불만 문의 {p!.negative_inquiries}건</>}
        </p>
      )}
      {p?.points_balance != null && <CustomerActions inquiryId={data.id} isAdmin={user?.role === "admin"} onDone={actionDone} />}
      <div className="mt-3 border-t border-hairline pt-3">
        <p className="mb-1.5 text-sm font-semibold text-body">이 고객의 다른 문의 {history.length ? `(${history.length})` : ""}</p>
        {/* 상담원: 남이 맡은 같은 고객 문의는 내용 없이 수만 (서로 다른 안내를 하지 않게) */}
        {!!data.customer_history_hidden?.total && (
          <p className={cx("mb-1.5 rounded-lg px-2.5 py-1.5 text-xs",
            data.customer_history_hidden.open ? "bg-amber-50 text-amber-900" : "bg-surface-soft text-muted")}>
            다른 상담원이 맡은(또는 미배정) 문의 {data.customer_history_hidden.total}건
            {data.customer_history_hidden.open > 0 && <> · <b>처리 중 {data.customer_history_hidden.open}건</b> — 안내가 겹치지 않게 관리자에게 확인해 주세요</>}
          </p>
        )}
        {history.length === 0 && !data.customer_history_hidden?.total ? <p className="text-sm text-muted">없음</p> : history.length === 0 ? null : (
          <>
            <ul className="space-y-1.5 text-sm">{history.slice(0, 3).map(historyRow)}</ul>
            {history.length > 3 && (
              <details className="group/more mt-1.5">
                <summary className="cursor-pointer list-none text-sm text-muted hover:text-primary">
                  <span className="group-open/more:hidden">{history.length - 3}건 더 보기 ▾</span><span className="hidden group-open/more:inline">접기 ▴</span>
                </summary>
                <ul className="mt-1.5 space-y-1.5 text-sm">{history.slice(3).map(historyRow)}</ul>
              </details>
            )}
          </>
        )}
      </div>
    </Fold>
  );
  // 주문을 확인해야 하는 문의인데 주문을 못 찾음: 주문 관련 유형 + 사람이 처리 (FAQ로 자동 답변한 일반 질문은 제외)
  const needsOrder = !!a && ORDER_CATEGORIES.includes(a.category) && a.decision !== "자동 답변" && !data.order?.found;
  const orderCard = <OrderInfo exchanged={data.tickets.some((t) => t.ticket_type === "교환" && t.status === "승인")} o={data.order} others={data.email_orders} hints={data.order_hints ?? []} category={a?.category ?? null} needsOrder={needsOrder}
    inquiryId={data.id} onDone={actionDone} />;
  // 주문 관련 문의(주문번호를 적었거나 이메일로 찾은 주문이 있음)는 주문 정보가 판단의 핵심 → 위에. 아니면 고객을 위에
  const orderFirst = !!data.order || needsOrder;

  return (
    <div className="space-y-4">
      {/* 상단 고정: 무엇을, 얼마나 급하게 + 바로 할 수 있는 처리.
          본문 판 위쪽에 딱 맞게 (판의 안쪽 여백만큼 바깥으로 넓혀 판 모서리와 맞춤), 스크롤하면 위쪽 판(검색·내 정보) 바로 아래에 붙음 */}
      <div className="sticky top-[var(--admin-header-bottom)] z-10 -mx-4 -mt-4 rounded-t-2xl border-b border-hairline bg-surface-soft/95 px-4 py-3 backdrop-blur lg:-mx-6 lg:-mt-6 lg:rounded-t-3xl lg:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <Link to="/admin/inquiries" className="inline-flex items-center gap-1 text-sm text-muted hover:text-primary">← 문의 목록</Link>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              <h1 className="page-title truncate">{data.title}</h1>
              {a?.urgency === "높음" && <span className="rounded-full bg-rose-600 px-2 py-0.5 text-sm font-semibold text-white">⚠ 긴급</span>}
              <Badge value={data.status} />
            </div>
            <p className="mt-1 flex flex-wrap items-center gap-y-1 text-sm text-muted">
              <span className="font-mono font-medium text-body">{data.inquiry_number}</span>
              <span className="mx-1.5">·</span>접수 {timeAgo(data.created_at)} ({formatDate(data.created_at)})
              <DueTime due={data.due_at} overdue={data.overdue} open={isOpen} />
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {queue && queue.total > 0 && (
              <span className="flex items-center gap-1" aria-label="처리 대기열">
                <Button variant="ghost" className="min-h-9 px-2.5 py-1" disabled={!queue.prev_id} title="이전 미처리 문의 (Alt+←)"
                  onClick={() => go(queue.prev_id)}>◀</Button>
                <span className="px-1 tabular-nums text-muted" title="미처리 대기열 (긴급도 → 오래된 순)">
                  {queue.position ? `${queue.position} / ${queue.total}` : `대기 ${queue.total}건`}
                </span>
                <Button variant="ghost" className="min-h-9 px-2.5 py-1" disabled={!queue.next_id} title="다음 미처리 문의 (Alt+→)"
                  onClick={() => go(queue.next_id)}>▶</Button>
              </span>
            )}
            <span className="ml-1 text-muted">담당</span>
            {user?.role === "admin" ? (
              <Select disabled={busy} value={data.assigned_to?.id ?? ""} aria-label="담당자"
                onChange={(e) => run(() => inquiryApi.assign(id, e.target.value ? Number(e.target.value) : null))}>
                <option value="">미배정</option>
                {staff.map((s) => <option key={s.id} value={s.id}>{staffLabel(s)}</option>)}
                {/* 담당자가 비활성 계정이면 목록에 없어 '미배정'으로 잘못 보이지 않게 */}
                {data.assigned_to && !staff.some((s) => s.id === data.assigned_to!.id) && (
                  <option value={data.assigned_to.id}>{data.assigned_to.display_name} (비활성 계정)</option>
                )}
              </Select>
            ) : (
              <>
                <span className="font-medium text-ink">{data.assigned_to?.display_name ?? "미배정"}</span>
                {!data.assigned_to && (
                  <Button disabled={busy} onClick={() => run(() => inquiryApi.assign(id, user!.id))}>내가 맡기</Button>
                )}
                {data.assigned_to?.id === user?.id && (
                  <Button variant="ghost" disabled={busy} onClick={() => setDialog("handover")}>넘기기</Button>
                )}
              </>
            )}
            {isOpen ? (
              <Button disabled={busy || (user?.role !== "admin" && data.assigned_to?.id !== user?.id)}
                onClick={() => setDialog("close")}>완료 처리</Button>
            ) : (
              <Button variant="ghost" disabled={busy} onClick={() => run(() => inquiryApi.setStatus(id, "담당자 처리"))}>다시 열기</Button>
            )}
          </div>
        </div>
        {actionError && <div className="mt-2"><Alert>{actionError}</Alert></div>}
        {user?.role !== "admin" && !data.assigned_to && (
          <div className="mt-2"><Alert kind="info">아직 담당자가 없는 문의예요. [내가 맡기]를 누르면 답변·처리할 수 있어요.</Alert></div>
        )}
        {dialog === "close" && (
          <CloseDialog answered={data.responses.some((r) => r.status === "발송")} onClose={() => setDialog(null)}
            onDone={(reason) => { setDialog(null); run(() => inquiryApi.setStatus(id, "완료", reason)); }} />
        )}
        {dialog === "handover" && user && (
          <HandoverDialog staff={staff} meId={user.id} onClose={() => setDialog(null)}
            onDone={(to, memo) => {
              setDialog(null);
              run(async () => { await inquiryApi.assign(id, to, memo); navigate("/admin/inquiries?open=true"); });
            }} />
        )}
        {notice && (
          <div className="mt-2"><Alert kind="success">
            {notice}
            {/* 처리 결과를 답변에 넣을 때: 안내만 하지 않고 그 자리에서 바로 (답변 칸의 [AI 초안 다시 만들기]와 같음) */}
            {notice.includes("AI 초안 다시 만들기") && (
              <button type="button" className="ml-2 rounded-lg border border-emerald-300 bg-white px-2 py-0.5 text-xs font-semibold text-emerald-800 hover:border-emerald-500"
                onClick={() => window.dispatchEvent(new Event("inquai:redraft"))}>AI 초안 다시 만들기</button>
            )}
          </Alert></div>
        )}
        {/* 처리가 끝난 문의: 다음 미처리 문의로 바로 (목록으로 돌아갔다 오지 않게) */}
        {!isOpen && queue?.next_id && (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
            <span>
              {data.recheck ? `답변은 보냈어요 (확인 후 다시 안내 ${formatDate(data.recheck.due_at)}까지).` : "이 문의는 처리됐어요."} 미처리 {queue.total}건이 남아 있습니다.
            </span>
            <Button className="min-h-9 px-4 py-1" onClick={() => go(queue.next_id)}>다음 미처리 문의 →</Button>
          </div>
        )}
      </div>

      <DecisionBanner d={data} />

      {/* 왼쪽(일하는 곳)이 넓게: 오른쪽 참고 정보는 고정 폭 (lg 22rem, xl 25rem) */}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_22rem] xl:grid-cols-[minmax(0,1fr)_25rem]">
        {/* 왼쪽: 일하는 곳 */}
        <div className="space-y-4">
          <Card title="문의와 답변">
            {/* key: 다른 문의로 옮기면 쓰던 답변·다시 안내 체크·요청을 모두 비움 (A 문의에 쓴 글이 B 고객에게 가지 않게) */}
            <AnswerComposer key={data.id} data={data} refFaqCodes={refFaqs.map(([code]) => code)} onChanged={load}
              onDirtyChange={(d) => { dirty.current = d; }} />
          </Card>

          <details className="group rounded-2xl border border-hairline bg-white">
            <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 text-lg font-semibold text-ink hover:bg-surface-soft">
              전체 처리 이력 <span className="text-sm font-normal text-muted">배정·상태 변경·알림 포함 · <span className="group-open:hidden">펼치기 ▾</span><span className="hidden group-open:inline">접기 ▴</span></span>
            </summary>
            <div className="border-t border-hairline px-5 py-4">
            <ol className="relative space-y-3 border-l border-hairline pl-4">
              {data.history.map((e, i) => (
                <li key={i} className="text-sm">
                  <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full bg-slate-300" />
                  <span className="text-xs text-muted">{formatDate(e.at)} · {e.actor}</span>
                  <p className="text-body">{e.text}</p>
                </li>
              ))}
            </ol>
            </div>
          </details>
        </div>

        {/* 오른쪽: 판단 근거 */}
        <div className="space-y-4">
          {/* 상담원 공유 메모: 상담원끼리 공유 (고객 대화와 따로, 답변을 쓰는 동안에도 보이게 맨 위) */}
          <InternalNotes key={data.id} data={data} onChanged={load} />
          {/* 취소·교환·반품 요청은 그 아래 (상담원이 가장 먼저 할 일). 처리한 뒤에도 같은 자리에 남겨 결과가 눈앞에서 사라지지 않게 */}
          {hasRequests && <Tickets data={data} onChanged={(m) => { setNotice(m); load(); }} />}
          {orderFirst ? <>{orderCard}{customerCard}</> : <>{customerCard}{orderCard}</>}

          {/* 요약 줄(유형·확신도·감정·긴급도)만으로 충분해 접어 둠. 확신도가 낮으면 유형을 확인해야 하니 펼침 */}
          <Fold id="analysis" title="AI 분석" defaultOpen={lowConf} summary={a ? `${a.category} (AI 확신 ${(a.confidence * 100).toFixed(0)}%)${lowConf ? " ⚠ 유형 판단 불확실" : ""} · ${a.sentiment} · 긴급도 ${a.urgency}` : "분석 전"}>
            {!a ? <p className="text-sm text-muted">분석 전</p> : (
              <>
                <dl className="grid grid-cols-[3.5rem_1fr] items-center gap-x-3 gap-y-1.5 text-sm">
                  <Row label="유형">
                    <span className="font-semibold">{a.category}</span>{" "}
                    <span className={cx(lowConf ? "font-semibold text-rose-700" : "text-muted")}>
                      AI 확신 {(a.confidence * 100).toFixed(0)}%{lowConf && " · 유형 판단 불확실, 유형이 맞는지 확인해 주세요"}
                    </span>
                  </Row>
                  <Row label="감정"><Badge value={a.sentiment} /></Row>
                  <Row label="긴급도"><Badge value={a.urgency} /></Row>
                </dl>
                {recheck?.changed && (
                  <p className="mt-2 text-xs text-muted">표기 오류 재확인: 분류 모델 '{recheck.model}' → AI '{recheck.llm}'</p>
                )}
                <details className="mt-3" open={lowConf}>
                  <summary className="cursor-pointer text-sm text-muted hover:text-primary">다른 유형 후보</summary>
                  <div className="mt-2 space-y-1">
                    {topScores.map(([label, prob]) => (
                      <div key={label} className="flex items-center gap-2 text-sm">
                        <span className="w-24 truncate text-muted">{label}</span>
                        <div className="h-1.5 flex-1 rounded bg-slate-100"><div className="h-1.5 rounded bg-indigo-400" style={{ width: `${Math.round(prob * 100)}%` }} /></div>
                        <span className="w-9 text-right tabular-nums text-muted">{(prob * 100).toFixed(0)}%</span>
                      </div>
                    ))}
                  </div>
                  <p className="mt-2 text-xs text-muted">모델 {a.model_version}</p>
                </details>
                <AnalysisEditor key={`${a.category}-${a.sentiment}`} data={data} onSaved={load} />
              </>
            )}
          </Fold>

          {!hasRequests && data.tickets.length > 0 && <Tickets data={data} onChanged={(m) => { setNotice(m); load(); }} />}

          {/* 도구·토큰·처리 시간 등 점검용 정보는 관리자에게만 */}
          {user?.role === "admin" && <AiDetails log={log} faqTitles={data.faq_titles} />}
        </div>
      </div>
    </div>
  );
}
