// 쇼핑몰 로그인 (/shop/login, 연동 시연용)
// 실제 서비스에서는 쇼핑몰의 로그인을 그대로 쓰므로 회원가입·비밀번호 찾기는 만들지 않았습니다.
import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";

import { useShop } from "../../auth/ShopProvider";
import { Alert, Button, Card, Field, Input, Spinner } from "../../components/ui";
import { errorMessage } from "../../services/api";

export default function ShopLoginPage() {
  const { customer, login } = useShop();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/my";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (customer) return <Navigate to={from} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(email.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card title="쇼핑몰 로그인">
        <form onSubmit={submit} className="space-y-4">
          <Field label="이메일">
            <Input required type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="비밀번호">
            <Input required type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {error && <Alert>{error}</Alert>}
          <Button type="submit" disabled={busy} className="w-full">{busy ? <Spinner /> : "로그인"}</Button>
        </form>
      </Card>
      <div className="rounded-xl border border-hairline bg-white/60 p-4 text-xs leading-relaxed text-muted">
        <p className="font-semibold text-body">쇼핑몰 로그인 연동 (시연)</p>
        <p className="mt-1">
          실제 서비스에서는 쇼핑몰에 로그인한 상태로 고객센터에 들어옵니다. 시연에서는 모의 고객 계정
          (customer01@example.com ~ customer20@example.com)으로 로그인합니다. 회원가입은 쇼핑몰에서 하므로 여기에는 없습니다.
        </p>
        <p className="mt-2">
          로그인하지 않아도 <Link to="/inquiry" className="text-primary hover:underline">비회원 문의</Link>를 남길 수 있어요.
        </p>
      </div>
    </div>
  );
}
