// 상담원 공유 메모 카드 (문의 상세 오른쪽 맨 위): 상담원끼리 공유하는 메모. 고객 비공개
// - 고객 대화와 섞지 않고 따로: 답변을 쓰는 동안에도 동료가 남긴 메모("택배사 확인 중")가 계속 보이게
// - 최신 메모가 위, 3개가 넘으면 [모두 보기]. 메모가 없으면 [+ 메모 남기기]만 작게 (주문 정보를 밀어내지 않게)
// - [크게 보기]: 화면 오른쪽 옆 패널에서 메모 전체를 넓게 보고 씀 (새 창 대신: 답변 화면과 어긋나지 않게)
// - 색: 연한 슬레이트(회색-파랑) = '참고 정보' (노랑은 '확인할 것'에 씀, DESIGN.md 색의 뜻)
// - 내가 맡은 문의에 다른 사람이 메모를 남기면 🔔 '새 상담원 공유 메모' 알림 (backend/api/notifications.py)
// - 'New' 배지: 이 문의를 마지막으로 본 뒤 다른 사람이 남긴 메모. 본 시각은 이 브라우저에 계정·문의별로 기억
//   (화면을 열 때의 기준으로 표시하고, 다음에 열 때는 지금 본 것으로 처리)
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { useAuth } from "../auth/AuthProvider";
import { errorMessage, inquiryApi } from "../services/api";
import type { InquiryDetail } from "../services/types";
import { Alert, Button, Spinner, Textarea, cx, formatDate } from "./ui";

const SHOW = 3;
type Note = InquiryDetail["notes"][number];

const seenKey = (userId: number, inquiryId: number) => `inquai:notes-seen:${userId}:${inquiryId}`;
function readSeen(key: string): number | null {
  try {
    const v = window.localStorage.getItem(key);
    return v ? Number(v) : null;
  } catch {
    return null;
  }
}
function writeSeen(key: string) {
  try {
    window.localStorage.setItem(key, String(Date.now()));
  } catch {
    /* 저장할 수 없는 브라우저면 'New' 기준만 매번 처음으로 */
  }
}

function PrivateTag() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-slate-200/80 px-2 py-0.5 text-xs font-medium text-slate-700"
      title="고객 화면·알림 메일에는 나가지 않아요">
      🔒 고객 비공개
    </span>
  );
}

function NewBadge({ count }: { count?: number }) {
  return <span className="rounded-full bg-primary px-1.5 py-0.5 text-xs font-bold text-white">New{count ? ` ${count}` : ""}</span>;
}

function NoteList({ notes, isNew }: { notes: Note[]; isNew: (n: Note) => boolean }) {
  return (
    <ul className="space-y-2">
      {notes.map((n) => (
        <li key={n.id} className={cx("rounded-xl border bg-white px-3 py-2 text-sm", isNew(n) ? "border-primary/40 ring-2 ring-primary/15" : "border-slate-200")}>
          <p className="flex items-center gap-1.5 text-xs text-muted">
            {isNew(n) && <NewBadge />}
            <b className="text-body">{n.author}</b> · {formatDate(n.created_at)}
          </p>
          <p className="mt-0.5 whitespace-pre-line text-body">{n.text}</p>
        </li>
      ))}
    </ul>
  );
}

/** 메모 입력칸 (카드·옆 패널 공통). Ctrl+Enter 로도 남김 */
function NoteForm({ busy, text, setText, onSave, onCancel, autoFocus }: {
  busy: boolean; text: string; setText: (v: string) => void; onSave: () => void; onCancel?: () => void; autoFocus?: boolean;
}) {
  return (
    <div className="space-y-2">
      <Textarea value={text} maxLength={2000} onChange={(e) => setText(e.target.value)} autoFocus={autoFocus} aria-label="상담원 공유 메모 내용"
        className="min-h-20 bg-white text-sm" disabled={busy}
        placeholder="상담원끼리 공유할 내용 (예: 택배사 확인 중, 내일 오전 재연락)"
        onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && text.trim() && !busy) { e.preventDefault(); onSave(); } }} />
      <div className="flex justify-end gap-2">
        {onCancel && <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={busy} onClick={onCancel}>취소</Button>}
        <Button className="min-h-9 px-4 py-1" disabled={busy || !text.trim()} onClick={onSave}>{busy ? <Spinner /> : "메모 남기기"}</Button>
      </div>
    </div>
  );
}

export default function InternalNotes({ data, onChanged }: { data: InquiryDetail; onChanged: () => void }) {
  const { user } = useAuth();
  const notes = [...data.notes].reverse();   // 최신이 위
  const key = user ? seenKey(user.id, data.id) : "";
  // 화면을 연 순간의 '마지막으로 본 시각' (처음 보는 문의면 0 → 다른 사람 메모는 모두 New)
  const [seenAt] = useState(() => (key ? readSeen(key) ?? 0 : Date.now()));
  useEffect(() => {
    if (key) writeSeen(key);
  }, [key, data.notes.length]);
  const isNew = (n: Note) => !!user && n.author_id !== user.id && new Date(n.created_at).getTime() > seenAt;
  const newCount = notes.filter(isNew).length;
  const [all, setAll] = useState(false);
  const [writing, setWriting] = useState(false);
  const [wide, setWide] = useState(false);   // [크게 보기] 옆 패널
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // 옆 패널: Esc 로 닫기
  useEffect(() => {
    if (!wide) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setWide(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [wide]);

  async function save() {
    setError("");
    setBusy(true);
    try {
      await inquiryApi.addNote(data.id, text.trim());
      setText("");
      setWriting(false);
      onChanged();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const title = (
    <h2 className="flex flex-wrap items-center gap-1.5 text-lg font-semibold text-ink">
      📝 상담원 공유 메모 {notes.length > 0 && <span className="font-normal text-muted">{notes.length}</span>}
      {newCount > 0 && <NewBadge count={newCount} />}
    </h2>
  );
  const shown = all ? notes : notes.slice(0, SHOW);

  return (
    <>
      <section className="rounded-2xl border border-slate-200 bg-slate-50 p-4" aria-label="상담원 공유 메모">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {title}
          <span className="flex items-center gap-2">
            <PrivateTag />
            <button type="button" onClick={() => setWide(true)} className="text-xs font-semibold text-primary hover:underline">크게 보기</button>
          </span>
        </div>

        {shown.length > 0 && <div className="mt-2"><NoteList notes={shown} isNew={isNew} /></div>}
        {notes.length > SHOW && (
          <button type="button" onClick={() => setAll(!all)} className="mt-1.5 text-xs font-semibold text-primary hover:underline">
            {all ? "최근 3개만 보기 ▴" : `모두 보기 (${notes.length}) ▾`}
          </button>
        )}

        <div className="mt-2">
          {writing && !wide ? (
            <NoteForm busy={busy} text={text} setText={setText} onSave={save} autoFocus
              onCancel={() => { setWriting(false); setText(""); }} />
          ) : (
            <button type="button" onClick={() => setWriting(true)}
              className="w-full rounded-xl border border-dashed border-slate-300 bg-white py-2 text-sm font-medium text-body hover:border-primary/40 hover:text-primary">
              + 메모 남기기
            </button>
          )}
        </div>
        {error && !wide && <div className="mt-2"><Alert>{error}</Alert></div>}
      </section>

      {/* [크게 보기] 옆 패널: 메모 전체 + 입력칸. 바깥·Esc·[닫기] 로 닫음 (보던 화면은 그대로).
          관리 화면 판에 흐림 효과가 있어 그 안에서는 화면 전체를 덮지 못하므로 body 에 띄움 */}
      {wide && createPortal(
        <div className="fixed inset-0 z-[90] flex justify-end bg-slate-900/30" onMouseDown={(e) => { if (e.target === e.currentTarget) setWide(false); }}>
          <aside role="dialog" aria-modal="true" aria-label="상담원 공유 메모 크게 보기"
            className="flex h-full w-full max-w-lg flex-col border-l border-slate-200 bg-slate-50 shadow-xl">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-5 py-4">
              <div>
                {title}
                <p className="mt-0.5 text-xs text-muted">{data.inquiry_number} · {data.title}</p>
              </div>
              <span className="flex items-center gap-2">
                <PrivateTag />
                <Button variant="ghost" className="min-h-9 px-3 py-1" onClick={() => setWide(false)}>닫기</Button>
              </span>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {notes.length ? <NoteList notes={notes} isNew={isNew} /> : <p className="text-sm text-muted">아직 메모가 없어요.</p>}
            </div>
            <div className="border-t border-slate-200 bg-white px-5 py-4">
              <NoteForm busy={busy} text={text} setText={setText} onSave={save} autoFocus />
              {error && <div className="mt-2"><Alert>{error}</Alert></div>}
            </div>
          </aside>
        </div>,
        document.body,
      )}
    </>
  );
}
