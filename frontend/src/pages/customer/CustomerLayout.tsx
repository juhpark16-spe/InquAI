import { NavLink, Outlet } from "react-router";

import { cx } from "../../components/ui";

export default function CustomerLayout() {
  const link = ({ isActive }: { isActive: boolean }) =>
    cx("rounded-md px-3 py-1.5 text-sm", isActive ? "bg-indigo-50 font-medium text-indigo-700" : "text-slate-600 hover:text-slate-900");
  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-2xl items-center justify-between px-4 py-3">
          <span className="font-semibold text-slate-900">InquAI 쇼핑 고객센터</span>
          <nav className="flex gap-1">
            <NavLink to="/faq" className={link}>자주 묻는 질문</NavLink>
            <NavLink to="/inquiry" end className={link}>문의하기</NavLink>
            <NavLink to="/inquiry/lookup" className={link}>문의 조회</NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  );
}
