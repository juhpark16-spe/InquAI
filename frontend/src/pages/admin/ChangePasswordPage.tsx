// 첫 로그인·비밀번호 초기화 뒤 새 비밀번호 정하기 (/change-password)
// 관리자가 정해 준 임시 비밀번호는 관리자도 알고 있으므로, 본인만 아는 비밀번호로 바꾼 뒤에 관리 화면을 씁니다.
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import { Alert, Button, Card, Field, Input, Spinner } from "../../components/ui";
import { authApi, errorMessage } from "../../services/api";

const EMPTY = { current: "", next: "", confirm: "" };

export default function ChangePasswordPage() {
  const { user, setUser, logout } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/admin";
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (user && !user.must_change_password) return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (form.next !== form.confirm) {
      setError("새 비밀번호 확인이 일치하지 않습니다.");
      return;
    }
    setBusy(true);
    try {
      setUser(await authApi.changePassword(form.current, form.next));
      navigate(from === "/change-password" ? "/admin" : from, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof EMPTY) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 py-8">
      <div className="text-center">
        <span className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-pink text-xl font-bold text-white" aria-hidden>Q</span>
        <h1 className="page-title">새 비밀번호 정하기</h1>
        <p className="mt-2 text-sm text-muted">{user?.display_name} ({user?.username})</p>
      </div>
      <Card className="w-full max-w-sm">
        <Alert kind="info">
          관리자가 정해 준 임시 비밀번호로 로그인했습니다. 본인만 아는 새 비밀번호로 바꿔야 관리 화면을 쓸 수 있습니다.
        </Alert>
        <form onSubmit={submit} className="mt-4 space-y-4">
          <Field label="임시 비밀번호" hint="관리자에게 받은 비밀번호">
            <Input required type="password" autoComplete="current-password" value={form.current} onChange={set("current")} />
          </Field>
          <Field label="새 비밀번호" hint="임시 비밀번호와 다르게, 최소 길이는 서버 설정을 따릅니다 (기본 8자).">
            <Input required type="password" autoComplete="new-password" value={form.next} onChange={set("next")} />
          </Field>
          <Field label="새 비밀번호 확인">
            <Input required type="password" autoComplete="new-password" value={form.confirm} onChange={set("confirm")} />
          </Field>
          {error && <Alert>{error}</Alert>}
          <Button type="submit" disabled={busy} className="w-full">{busy ? <Spinner /> : "비밀번호 바꾸고 시작하기"}</Button>
          <button type="button" className="w-full text-center text-sm text-muted hover:text-ink"
            onClick={async () => { await logout(); navigate("/login", { replace: true }); }}>
            나중에 하기 (로그아웃)
          </button>
        </form>
      </Card>
    </div>
  );
}
