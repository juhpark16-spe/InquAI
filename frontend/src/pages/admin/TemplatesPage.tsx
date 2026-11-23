// 답변 문구 관리 (/admin/templates, 관리자): 상담원이 답변 칸의 [문구 넣기]로 쓰는 자주 쓰는 문장
// - 문구마다 이름(버튼에 보이는 말)과 문장, 사용/숨김, 순서(▲▼)를 고침. 바뀐 내용은 작업 기록에 남음
// - 문장은 FAQ·쇼핑몰 정책(docs/shop_policy.md)과 같은 내용만 쓰도록 안내 (고객에게 잘못된 약속을 하지 않게)
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { confirmDialog } from "../../components/ConfirmDialog";
import { Alert, Button, Card, Field, Input, Spinner, Textarea, cx } from "../../components/ui";
import { errorMessage, templateApi, type ReplyTemplate } from "../../services/api";

function Row({ t, first, last, onMove, onSaved, onError }: {
  t: ReplyTemplate; first: boolean; last: boolean;
  onMove: (dir: -1 | 1) => void; onSaved: (msg: string) => void; onError: (msg: string) => void;
}) {
  const [label, setLabel] = useState(t.label);
  const [text, setText] = useState(t.text);
  const [busy, setBusy] = useState(false);
  const dirty = label.trim() !== t.label || text.trim() !== t.text;

  async function act(fn: () => Promise<unknown>, msg: string) {
    setBusy(true);
    try {
      await fn();
      onSaved(msg);
    } catch (err) {
      onError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  // 한 줄: 순서 ▲▼ · 이름 · (숨김) · 버튼 / 아래: 문장 (짧은 문장이 많아 칸을 낮게)
  return (
    <li className={cx("rounded-2xl border bg-white px-4 py-3", t.is_active ? "border-hairline" : "border-dashed border-slate-300 bg-slate-50/70")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex gap-1" aria-label="순서">
          <button type="button" className="h-8 w-8 rounded-md border border-hairline text-sm text-muted hover:text-primary disabled:opacity-30"
            disabled={first || busy} onClick={() => onMove(-1)} title="위로">▲</button>
          <button type="button" className="h-8 w-8 rounded-md border border-hairline text-sm text-muted hover:text-primary disabled:opacity-30"
            disabled={last || busy} onClick={() => onMove(1)} title="아래로">▼</button>
        </span>
        <Input value={label} maxLength={20} onChange={(e) => setLabel(e.target.value)} disabled={busy}
          className="min-h-9! w-44! flex-none py-1.5 font-semibold" aria-label="문구 이름" />
        {!t.is_active && <span className="rounded-full bg-slate-200 px-2 py-0.5 text-xs text-slate-600">숨김 · 답변 칸에 안 보임</span>}
        <span className="ml-auto flex gap-1.5">
          <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={busy} onClick={async () => {
            if (await confirmDialog({ title: "답변 문구 삭제", confirmLabel: "삭제", tone: "danger",
              message: `'${t.label}' 문구를 지울까요?\n지운 기록은 작업 기록에 남습니다. 잠깐 쓰지 않을 거라면 [숨기기]를 쓰세요.` })) {
              act(() => templateApi.remove(t.id), "문구를 지웠습니다.");
            }
          }}>삭제</Button>
          <Button variant="ghost" className="min-h-9 px-3 py-1" disabled={busy} onClick={() => act(() => templateApi.update(t.id, { is_active: !t.is_active }),
            t.is_active ? "문구를 숨겼습니다. 답변 칸에 보이지 않아요." : "문구를 다시 사용합니다.")}>
            {t.is_active ? "숨기기" : "다시 사용"}
          </Button>
          <Button className="min-h-9 px-4 py-1" disabled={busy || !dirty || !label.trim() || text.trim().length < 2}
            onClick={() => act(() => templateApi.update(t.id, { label: label.trim(), text: text.trim() }), "문구를 저장했습니다.")}>
            {busy ? <Spinner /> : "저장"}
          </Button>
        </span>
      </div>
      <Textarea value={text} maxLength={500} rows={2} onChange={(e) => setText(e.target.value)} disabled={busy}
        className="mt-2 min-h-0! text-sm" aria-label="문장" />
    </li>
  );
}

export default function TemplatesPage() {
  const [items, setItems] = useState<ReplyTemplate[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [label, setLabel] = useState("");
  const [text, setText] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => templateApi.list(true).then(setItems).catch((err) => setError(errorMessage(err))), []);
  useEffect(() => { load(); }, [load]);

  const saved = (msg: string) => { setError(""); setNotice(msg); load(); };

  async function move(index: number, dir: -1 | 1) {
    if (!items) return;
    const ids = items.map((t) => t.id);
    [ids[index], ids[index + dir]] = [ids[index + dir], ids[index]];
    try {
      setItems(await templateApi.reorder(ids));
      setNotice("순서를 바꿨습니다.");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function add(e: FormEvent) {
    e.preventDefault();
    setAdding(true);
    try {
      await templateApi.create(label.trim(), text.trim());
      setLabel("");
      setText("");
      saved("문구를 추가했습니다. 답변 칸의 [문구 넣기] 맨 뒤에 보여요.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="page-title">답변 문구</h1>
        <p className="mt-1 text-sm text-muted">
          상담원이 답변을 쓸 때 [문구·주문 정보 넣기]에서 한 번에 넣는 문장입니다. FAQ·쇼핑몰 정책과 같은 내용만 써 주세요
          (기간·금액을 잘못 적으면 고객에게 그대로 안내됩니다). 바꾼 내용은 작업 기록에 남습니다.
        </p>
      </div>
      {error && <Alert>{error}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}

      {!items ? <p className="text-center text-muted"><Spinner /></p> : (
        <ul className="space-y-3">
          {items.map((t, i) => (
            <Row key={`${t.id}-${t.label}-${t.text}-${t.is_active}`} t={t} first={i === 0} last={i === items.length - 1}
              onMove={(dir) => move(i, dir)} onSaved={saved} onError={setError} />
          ))}
          {items.length === 0 && <li className="text-sm text-muted">등록된 문구가 없습니다.</li>}
        </ul>
      )}

      <Card title="새 문구">
        <form onSubmit={add} className="space-y-3">
          <Field label="이름" hint="버튼에 보이는 짧은 말 (20자까지). 예: 배송 지연 사과">
            <Input value={label} maxLength={20} onChange={(e) => setLabel(e.target.value)} required disabled={adding} />
          </Field>
          <Field label="문장" hint="답변 칸의 커서 자리에 들어가는 문장 (500자까지)">
            <Textarea value={text} maxLength={500} onChange={(e) => setText(e.target.value)} required minLength={2}
              className="min-h-20" disabled={adding} />
          </Field>
          <div className="flex justify-end">
            <Button type="submit" disabled={adding || !label.trim() || text.trim().length < 2}>{adding ? <Spinner /> : "추가"}</Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
