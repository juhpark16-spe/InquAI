// 내 문의 조회 (/inquiry/lookup): 비회원은 이메일 + 조회 비밀번호로 내 문의를 대화형으로 보고,
// 답변 평가(도움이 되었나요?)와 추가 문의를 남길 수 있음. 비밀번호는 이 화면 안에서만 기억(저장하지 않음)
// 쇼핑몰에 로그인한 고객은 비밀번호 없이 '내 쇼핑'(/my)에서 봅니다.
import { useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router";

import { useShop } from "../../auth/ShopProvider";
import InquiryThreads from "../../components/InquiryThreads";
import { Alert, Button, Card, Field, Input, Spinner } from "../../components/ui";
import { customerApi, errorMessage } from "../../services/api";
import type { InquiryPublic } from "../../services/types";

export default function InquiryLookupPage() {
  const { customer } = useShop();
  const fromForm = (useLocation().state as { email?: string } | null)?.email ?? "";
  const [email, setEmail] = useState(fromForm);
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [items, setItems] = useState<InquiryPublic[] | null>(null);
  const [notice, setNotice] = useState("");

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

  return (
    <div className="space-y-4">
      {customer && (
        <Alert kind="info">
          {customer.name}님은 쇼핑몰에 로그인되어 있어요. <Link to="/my" className="font-semibold underline">내 쇼핑</Link>에서
          비밀번호 없이 내 문의를 볼 수 있습니다.
        </Alert>
      )}
      <Card title="내 문의 조회 (비회원)">
        <form onSubmit={submit} className="space-y-4">
          <Field label="문의할 때 쓴 이메일">
            <Input required type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="조회 비밀번호" hint="문의할 때 정한 비밀번호입니다. 비밀번호가 다르게 작성된 문의는 따로 조회됩니다.">
            <Input required type="password" autoComplete="current-password" autoFocus={!!fromForm}
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

      {items && <p className="text-sm text-slate-600">문의 {items.length}건 (최신순) · {notice}</p>}
      {items && (
        <InquiryThreads items={items} notice={notice} reload={load} actions={{
          rate: (n, id, helpful) => customerApi.rate(id, n, email.trim(), password, helpful),
          followUp: (n, text, tokens) => customerApi.followUp(email.trim(), password, n, text, tokens),
        }} />
      )}
    </div>
  );
}
