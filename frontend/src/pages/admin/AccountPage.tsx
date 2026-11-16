// 내 계정 (/admin/account): 관리자·상담원이 자기 비밀번호를 바꿈
import { useState, type FormEvent } from "react";

import { useAuth } from "../../auth/AuthProvider";
import { Alert, Button, Card, Field, Input, Spinner } from "../../components/ui";
import { authApi, errorMessage } from "../../services/api";

const EMPTY = { current: "", next: "", confirm: "" };

export default function AccountPage() {
  const { user } = useAuth();
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setDone(false);
    if (form.next !== form.confirm) {
      setError("새 비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    setBusy(true);
    try {
      await authApi.changePassword(form.current, form.next);
      setForm(EMPTY);
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="mx-auto max-w-md space-y-4">
      <h1 className="text-lg font-semibold text-slate-900">내 계정</h1>
      <Card>
        <dl className="grid grid-cols-[5rem_1fr] gap-y-1 text-sm">
          <dt className="text-slate-500">이름</dt><dd>{user?.display_name}</dd>
          <dt className="text-slate-500">아이디</dt><dd className="font-mono">{user?.username}</dd>
          <dt className="text-slate-500">역할</dt><dd>{user?.role === "admin" ? "관리자" : "상담원"}</dd>
        </dl>
      </Card>
      <Card title="비밀번호 변경">
        <form onSubmit={submit} className="space-y-3">
          <Field label="현재 비밀번호">
            <Input required type="password" autoComplete="current-password" value={form.current} onChange={set("current")} />
          </Field>
          <Field label="새 비밀번호" hint="비밀번호를 바꾸면 다른 기기에서의 로그인은 모두 끊깁니다.">
            <Input required type="password" autoComplete="new-password" value={form.next} onChange={set("next")} />
          </Field>
          <Field label="새 비밀번호 확인">
            <Input required type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
          </Field>
          {error && <Alert>{error}</Alert>}
          {done && <Alert kind="success">비밀번호를 바꿨습니다. 다음 로그인부터 새 비밀번호를 쓰세요.</Alert>}
          <Button type="submit" disabled={busy} className="w-full">{busy ? <Spinner /> : "비밀번호 변경"}</Button>
        </form>
      </Card>
    </div>
  );
}
