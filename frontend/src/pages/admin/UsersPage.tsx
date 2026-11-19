// 계정 관리 (/admin/users, 관리자만): 상담원 계정 만들기, 이름·역할 변경, 비활성화, 비밀번호 초기화
// 공개 회원가입은 없고 관리자만 계정을 만듭니다 (기획서 6장).
import { useCallback, useEffect, useState, type FormEvent } from "react";

import { useAuth } from "../../auth/AuthProvider";
import { Alert, Badge, Button, Card, Field, Input, Select, Spinner, cx, formatDate } from "../../components/ui";
import { errorMessage, userApi } from "../../services/api";
import { CATEGORIES, type Role, type UserDetail } from "../../services/types";

const EMPTY = { username: "", display_name: "", role: "agent" as Role, password: "", categories: [] as string[] };
const ROLE_LABEL: Record<string, string> = { admin: "관리자", agent: "상담원" };

/** 담당 유형 고르기 (아무것도 고르지 않으면 전체 담당) */
function CategoryPicker({ value, onChange, disabled }: { value: string[]; onChange: (v: string[]) => void; disabled?: boolean }) {
  const toggle = (c: string) => onChange(value.includes(c) ? value.filter((x) => x !== c) : [...value, c]);
  return (
    <div className="flex flex-wrap gap-1.5">
      {CATEGORIES.map((c) => (
        <button key={c} type="button" disabled={disabled} onClick={() => toggle(c)} aria-pressed={value.includes(c)}
          className={cx("rounded-full border px-2.5 py-0.5 text-xs",
            value.includes(c) ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 bg-white text-slate-600 hover:border-slate-400")}>
          {c}
        </button>
      ))}
    </div>
  );
}

function CategoryChips({ categories }: { categories: string[] }) {
  if (!categories.length) return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">전체 담당</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {categories.map((c) => <span key={c} className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">{c}</span>)}
    </span>
  );
}

function CreateForm({ onCreated }: { onCreated: (u: UserDetail) => void }) {
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      const u = await userApi.create({ ...form, username: form.username.trim(), categories: form.role === "agent" ? form.categories : [] });
      setForm(EMPTY);
      onCreated(u);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="계정 만들기">
      <form onSubmit={submit} className="space-y-3">
        <Field label="아이디" hint="영문 소문자·숫자·밑줄(_) 3~30자">
          <Input required pattern="[a-z0-9_]{3,30}" autoComplete="off" value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </Field>
        <Field label="화면 이름" hint="배정 목록에 보이는 이름. 예: 상담원 박서준">
          <Input required maxLength={50} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        </Field>
        <Field label="역할">
          <Select className="w-full" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            <option value="agent">상담원 (배정된 문의만)</option>
            <option value="admin">관리자 (전체)</option>
          </Select>
        </Field>
        {form.role === "agent" && (
          <div className="space-y-1">
            <span className="text-sm font-medium text-slate-700">담당 유형</span>
            <CategoryPicker value={form.categories} onChange={(categories) => setForm({ ...form, categories })} />
            <span className="block text-xs text-slate-500">고른 유형의 문의가 자동 배정됩니다. 비워 두면 담당자가 없는 유형을 받는 전체 담당입니다.</span>
          </div>
        )}
        <Field label="임시 비밀번호" hint="계정 주인에게 따로 전달해 주세요. 첫 로그인 때 본인이 새 비밀번호로 바꿔야 관리 화면을 쓸 수 있습니다 (최소 길이는 서버 설정, 기본 8자).">
          <Input required type="password" autoComplete="new-password" value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </Field>
        {error && <Alert>{error}</Alert>}
        <Button type="submit" disabled={busy} className="w-full">{busy ? <Spinner /> : "계정 만들기"}</Button>
      </form>
    </Card>
  );
}

function UserRow({ u, isMe, onChanged }: { u: UserDetail; isMe: boolean; onChanged: (msg: string) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resetting, setResetting] = useState(false);
  const [password, setPassword] = useState("");
  const [editing, setEditing] = useState(false);
  const [cats, setCats] = useState(u.categories);
  const locked = u.locked_until && new Date(u.locked_until) > new Date();

  async function run(action: () => Promise<unknown>, msg: string): Promise<boolean> {
    setError("");
    setBusy(true);
    try {
      await action();
      onChanged(msg);
      setResetting(false);
      setPassword("");
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <tr className={cx("align-top", !u.is_active && "bg-slate-50 text-slate-400")}>
      <td className="whitespace-nowrap px-3 py-3">
        <div className="font-medium text-slate-900">{u.display_name}{isMe && <span className="ml-1 text-xs text-indigo-600">(나)</span>}</div>
        <div className="font-mono text-xs text-slate-500">{u.username}</div>
      </td>
      <td className="px-3 py-3">
        <Select disabled={busy || isMe || !u.is_active} value={u.role} aria-label="역할"
          onChange={(e) => run(() => userApi.update(u.id, { role: e.target.value as Role }), `${u.display_name}: 역할을 바꿨습니다.`)}>
          <option value="agent">상담원</option>
          <option value="admin">관리자</option>
        </Select>
      </td>
      <td className="min-w-48 px-3 py-3">
        {u.role !== "agent" ? <span className="text-xs text-slate-400">자동 배정 안 받음</span> : editing ? (
          <div className="space-y-2">
            <CategoryPicker value={cats} onChange={setCats} disabled={busy} />
            <div className="flex gap-2">
              <Button disabled={busy} className="px-3 py-1"
                onClick={() => run(() => userApi.update(u.id, { categories: cats }), `${u.display_name}: 담당 유형을 바꿨습니다.`).then((ok) => ok && setEditing(false))}>
                저장
              </Button>
              <Button variant="ghost" className="px-3 py-1" onClick={() => { setEditing(false); setCats(u.categories); }}>취소</Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <CategoryChips categories={u.categories} />
            {u.is_active && <button className="text-xs text-indigo-600 hover:underline" onClick={() => setEditing(true)}>수정</button>}
          </div>
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-3">
        {u.is_active ? <Badge value={locked ? "잠김" : "활성"} /> : <Badge value="비활성" />}
        {u.is_active && u.must_change_password && (
          <div className="mt-1 text-xs text-amber-700" title="임시 비밀번호 상태: 다음 로그인 때 본인이 새 비밀번호를 정해야 합니다">비밀번호 변경 전</div>
        )}
        {locked && <div className="mt-1 text-xs text-rose-600">{formatDate(u.locked_until)}까지</div>}
      </td>
      <td className="whitespace-nowrap px-3 py-3 text-slate-500">{formatDate(u.last_login_at)}</td>
      <td className="px-3 py-3">
        <div className="flex flex-wrap gap-2">
          {!isMe && (
            <Button variant={u.is_active ? "ghost" : "primary"} disabled={busy}
              onClick={() => {
                if (u.is_active && !window.confirm(`${u.display_name} 계정을 비활성화할까요? 바로 로그아웃되고 로그인할 수 없게 됩니다.`)) return;
                run(() => userApi.update(u.id, { is_active: !u.is_active }),
                  `${u.display_name}: ${u.is_active ? "비활성화했습니다." : "다시 활성화했습니다."}`);
              }}>
              {u.is_active ? "비활성화" : "활성화"}
            </Button>
          )}
          <Button variant="ghost" disabled={busy} onClick={() => setResetting(!resetting)}>
            {locked ? "비밀번호 초기화·잠금 해제" : "비밀번호 초기화"}
          </Button>
        </div>
        {resetting && (
          <form className="mt-2 flex gap-2"
            onSubmit={(e) => { e.preventDefault(); run(() => userApi.resetPassword(u.id, password), `${u.display_name}: 비밀번호를 바꿨습니다.`); }}>
            <Input required type="password" autoComplete="new-password" placeholder="임시 비밀번호 (다음 로그인 때 본인이 바꿈)"
              value={password} onChange={(e) => setPassword(e.target.value)} />
            <Button type="submit" disabled={busy}>저장</Button>
          </form>
        )}
        {error && <div className="mt-2"><Alert>{error}</Alert></div>}
      </td>
    </tr>
  );
}

export default function UsersPage() {
  const { user } = useAuth();
  const [users, setUsers] = useState<UserDetail[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(() => {
    userApi.list().then(setUsers).catch((err) => setError(errorMessage(err)));
  }, []);
  useEffect(load, [load]);

  const changed = (msg: string) => { setNotice(msg); load(); };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="page-title">계정 관리</h1>
        <p className="text-sm text-slate-500">관리자·상담원 계정은 이 화면에서만 만듭니다. 비활성화한 계정은 즉시 로그아웃되고 배정 목록에서 빠집니다.</p>
        <p className="mt-1 text-sm text-slate-500">
          AI가 사람에게 넘긴 문의는 <b className="font-medium text-slate-700">담당 유형이 맞는 상담원 중 미처리가 가장 적은 사람</b>에게 자동 배정됩니다.
          맞는 상담원이 없으면 전체 담당에게, 전체 담당도 없으면 미배정으로 남습니다.
        </p>
      </div>
      {error && <Alert>{error}</Alert>}
      {notice && <Alert kind="success">{notice}</Alert>}

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-sm text-slate-500">
              <tr>{["이름·아이디", "역할", "담당 유형 (자동 배정)", "상태", "마지막 로그인", "관리"].map((h) => <th key={h} className="px-3 py-2 font-medium">{h}</th>)}</tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users?.map((u) => <UserRow key={u.id} u={u} isMe={u.id === user?.id} onChanged={changed} />)}
            </tbody>
          </table>
          {!users && !error && <p className="p-6 text-center text-slate-500"><Spinner /></p>}
          <p className="border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
            총 {users?.length ?? 0}개 · {ROLE_LABEL.agent} {users?.filter((u) => u.role === "agent" && u.is_active).length ?? 0}명 활성
          </p>
        </div>
        <CreateForm onCreated={(u) => changed(`${u.display_name}(${u.username}) 계정을 만들었습니다.`)} />
      </div>
    </div>
  );
}
