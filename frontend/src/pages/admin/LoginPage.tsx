// 관리자·상담원 로그인 (/login). 실패·잠금 메시지는 서버가 준 문장을 그대로 보여 줍니다.
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import { Alert, Button, Card, Field, Input, Spinner, formatDate } from "../../components/ui";
import { errorCode, errorMessage } from "../../services/api";
import axios from "axios";

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/admin";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  if (user) return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      let msg = errorMessage(err);
      if (errorCode(err) === "ACCOUNT_LOCKED" && axios.isAxiosError(err) && err.response?.data?.locked_until) {
        msg += ` (해제 시각: ${formatDate(err.response.data.locked_until)})`;
      }
      setError(msg);
      setPassword("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <Card className="w-full max-w-sm" title="InquAI 관리자 로그인">
        <form onSubmit={submit} className="space-y-4">
          <Field label="아이디">
            <Input required autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          </Field>
          <Field label="비밀번호">
            <Input required type="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {error && <Alert>{error}</Alert>}
          <Button type="submit" disabled={loading} className="w-full">{loading ? <Spinner /> : "로그인"}</Button>
        </form>
      </Card>
    </div>
  );
}
