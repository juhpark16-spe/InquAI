// 내 문의 조회 (/inquiry/lookup): 비회원은 이메일 + 조회 비밀번호로 내 문의를 대화형으로 보고,
// 답변 평가(도움이 되었나요?)와 추가 문의를 남길 수 있음. 비밀번호는 이 화면 안에서만 기억(저장하지 않음)
// - 로그인 상태는 제목 옆 배지(비회원 / 회원 · ○○님)와 오른쪽 위 메뉴(로그인 · 내 쇼핑)에서
// - 조회에 성공하면 입력 카드를 한 줄 띠(이메일 · 건수 · 답변 상태 · [다른 이메일로 조회] [조회 끝내기])로 접고 결과로 내려감
// - [조회 끝내기]: 결과와 입력한 비밀번호를 지우고 처음으로 (공용 PC)
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router";

import { useShop } from "../../auth/ShopProvider";
import InquiryThreads from "../../components/InquiryThreads";
import { Alert, Button, Card, Field, Input, MemberBadge, Spinner } from "../../components/ui";
import { customerApi, errorMessage } from "../../services/api";
import type { InquiryPublic } from "../../services/types";

/** 고객에게 보이는 상태 (InquiryThreads 와 같은 기준: 마지막 글이 고객 것이면 '답변 준비 중') */
const closed = (i: InquiryPublic) => i.status === "완료" && !!i.closed_note;
function waiting(i: InquiryPublic) {
  if (closed(i)) return false;
  const mine = Math.max(new Date(i.created_at).getTime(), ...i.messages.map((m) => new Date(m.at).getTime()));
  const answered = Math.max(0, ...i.answers.map((a) => new Date(a.answered_at).getTime()));
  return mine > answered;
}

export default function InquiryLookupPage() {
  const { customer } = useShop();
  const fromForm = (useLocation().state as { email?: string } | null)?.email ?? "";
  const [email, setEmail] = useState(fromForm);
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [items, setItems] = useState<InquiryPublic[] | null>(null);
  const [notice, setNotice] = useState("");
  const results = useRef<HTMLDivElement>(null);

  async function load() {
    const r = await customerApi.lookup(email.trim(), password);
    setItems(r.items);
    setNotice(r.notice);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setItems(null);
    setLoading(true);
    try {
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  // 조회 결과가 나오면 결과 위치로 (휴대폰에서 첫 화면에 답변이 보이게)
  useEffect(() => {
    if (items) results.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [items === null]); // eslint-disable-line react-hooks/exhaustive-deps

  /** 다른 이메일로 조회: 결과를 닫고 입력 카드로 (이메일은 남기고 비밀번호는 지움) */
  function again() {
    setItems(null);
    setPassword("");
    setError("");
  }

  /** 조회 끝내기: 결과·이메일·비밀번호를 모두 지움 (공용 PC) */
  function finish() {
    again();
    setEmail("");
    setNotice("");
  }

  const pending = items?.filter((i) => waiting(i)).length ?? 0;
  const more = items?.filter((i) => !waiting(i) && !closed(i) && i.more_answer_coming).length ?? 0;
  const ended = items?.filter(closed).length ?? 0;
  const done = (items?.length ?? 0) - pending - more - ended;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title flex flex-wrap items-center gap-2">내 문의 조회 <MemberBadge name={customer?.name} /></h1>
        <p className="mt-1 text-sm text-muted">문의할 때 쓴 이메일과 조회 비밀번호로 답변을 확인하세요.</p>
      </div>

      {/* 회원 문의는 조회 비밀번호 없이 저장되므로 여기서는 찾을 수 없음 → 내 쇼핑으로 안내 */}
      {customer && !items && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-primary/30 bg-primary-soft px-5 py-4">
          <p className="text-sm text-ink">
            <b>{customer.name}님</b>이 로그인한 상태로 남긴 문의는 <b>내 쇼핑 &gt; 내 문의</b>에서 비밀번호 없이 바로 볼 수 있어요.
            <span className="block text-xs text-muted">아래 조회는 로그인하지 않고(비회원으로) 남긴 문의를 찾을 때 써요.</span>
          </p>
          <Link to="/my" className="whitespace-nowrap rounded-full bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary/90">내 문의 보기</Link>
        </div>
      )}

      {items ? (
        /* 조회 뒤: 입력 카드 대신 한 줄 띠 (결과가 나오면 이 띠가 화면 위에 오도록 내려감, 위쪽 메뉴 높이만큼 띄움) */
        <div ref={results} className="flex scroll-mt-28 flex-wrap items-center justify-between gap-3 rounded-2xl border border-hairline bg-white px-5 py-3.5">
          <div className="min-w-0 text-sm">
            <p className="truncate font-semibold text-ink">{email.trim()}의 문의 {items.length}건</p>
            <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted">
              {pending > 0 && <span className="font-semibold text-primary">답변 준비 중 {pending}</span>}
              {more > 0 && <span className="font-semibold text-primary">추가 안내 예정 {more}</span>}
              {done > 0 && <span className="text-emerald-700">답변 완료 {done}</span>}
              {ended > 0 && <span>종료됨 {ended}</span>}
              <span>· 최신순, 누르면 펼쳐져요</span>
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button variant="ghost" className="min-h-9 px-3.5 py-1.5" onClick={again}>다른 이메일로 조회</Button>
            <Button variant="ghost" className="min-h-9 px-3.5 py-1.5" onClick={finish}
              title="조회 결과와 입력한 비밀번호를 지웁니다 (여러 사람이 쓰는 PC라면 눌러 주세요)">조회 끝내기</Button>
          </div>
        </div>
      ) : (
        <Card>
          <form onSubmit={submit} className="space-y-4">
            <Field label="문의할 때 쓴 이메일">
              <Input required type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="조회 비밀번호" hint="문의할 때 정한 비밀번호예요. 문의마다 비밀번호를 다르게 정했다면, 그 비밀번호로 각각 조회돼요.">
              <Input required type="password" autoComplete="current-password" autoFocus={!!fromForm || (!!email && !password)}
                value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            {error && <Alert>{error}</Alert>}
            <Button type="submit" disabled={loading}>{loading ? <Spinner /> : "조회"}</Button>
          </form>
          <p className="mt-4 text-xs text-slate-500">
            비밀번호가 기억나지 않으면 <Link to="/inquiry" className="text-indigo-600 hover:underline">새 문의</Link>에
            이전 문의 내용을 함께 적어 주세요. 담당자가 확인해 드립니다.
          </p>
        </Card>
      )}

      {items && (
        <InquiryThreads items={items} notice={notice} reload={load} actions={{
          rate: (n, id, helpful) => customerApi.rate(id, n, email.trim(), password, helpful),
          followUp: (n, text, tokens, order) => customerApi.followUp(email.trim(), password, n, text, tokens, order),
        }} />
      )}
    </div>
  );
}
