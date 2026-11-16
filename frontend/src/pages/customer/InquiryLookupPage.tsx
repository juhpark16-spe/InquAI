// 내 문의 조회 (/inquiry/lookup): 이메일 + 문의할 때 정한 비밀번호로 내 문의 목록과 답변 확인
import { useState, type FormEvent } from "react";
import { Link, useLocation } from "react-router";

import { Alert, Badge, Button, Card, Field, Input, Spinner, formatDate } from "../../components/ui";
import { customerApi, errorMessage } from "../../services/api";
import type { InquiryPublic } from "../../services/types";

export default function InquiryLookupPage() {
  const fromForm = (useLocation().state as { email?: string } | null)?.email ?? "";
  const [email, setEmail] = useState(fromForm);
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [items, setItems] = useState<InquiryPublic[] | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setItems(null);
    setLoading(true);
    try {
      setItems(await customerApi.lookup(email.trim(), password));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
      setPassword("");
    }
  }

  return (
    <div className="space-y-4">
      <Card title="내 문의 조회">
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

      {items && (
        <p className="text-sm text-slate-600">문의 {items.length}건 (최신순)</p>
      )}
      {items?.map((found) => (
        <Card key={found.inquiry_number} title={found.title}>
          <div className="mb-3 flex flex-wrap items-center gap-2 text-sm text-slate-500">
            <Badge value={found.status} />
            <span>{formatDate(found.created_at)}</span>
            <span className="font-mono text-xs">{found.inquiry_number}</span>
          </div>
          <p className="mb-4 whitespace-pre-line text-sm text-slate-700">{found.content}</p>
          {found.answer ? (
            <div className="space-y-1">
              <p className="text-sm font-medium text-emerald-700">답변 ({formatDate(found.answered_at)})</p>
              <p className="whitespace-pre-line rounded-lg bg-emerald-50 p-4 text-sm leading-relaxed">{found.answer}</p>
            </div>
          ) : (
            <Alert kind="info">담당자가 확인하고 있습니다. 답변이 등록되면 이 화면에서 확인하실 수 있습니다.</Alert>
          )}
        </Card>
      ))}
    </div>
  );
}
