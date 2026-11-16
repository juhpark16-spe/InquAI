import { NavLink, Outlet, useNavigate } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import { cx } from "../../components/ui";

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const link = ({ isActive }: { isActive: boolean }) =>
    cx("whitespace-nowrap rounded-md px-3 py-1.5 text-sm", isActive ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-600 hover:text-slate-900");

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <div className="flex items-center gap-4">
            <span className="whitespace-nowrap font-semibold text-slate-900">InquAI 관리</span>
            <nav className="flex gap-1">
              {user?.role === "admin" && <NavLink to="/admin" end className={link}>대시보드</NavLink>}
              <NavLink to="/admin/inquiries" className={link}>문의 관리</NavLink>
              {user?.role === "admin" && <NavLink to="/admin/users" className={link}>계정 관리</NavLink>}
            </nav>
          </div>
          <div className="flex items-center gap-3 whitespace-nowrap text-sm">
            <NavLink to="/admin/account" title="내 계정 · 비밀번호 변경"
              className={({ isActive }) => cx("rounded-md px-2 py-1 hover:bg-slate-50", isActive ? "text-indigo-700" : "text-slate-600")}>
              {user?.display_name} <span className="text-slate-400">({user?.role === "admin" ? "관리자" : "상담원"})</span>
              <span className="ml-1 text-xs text-slate-400">· 내 계정</span>
            </NavLink>
            <button className="text-slate-500 hover:text-slate-900"
              onClick={async () => { await logout(); navigate("/login", { replace: true }); }}>
              로그아웃
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
