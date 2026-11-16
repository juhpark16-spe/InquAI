// 관리자 화면 틀: 왼쪽 사이드바(메뉴 + 미처리 건수) / 오른쪽 위 로그인한 사람·로그아웃 / 본문
// 좁은 화면(lg 미만)에서는 사이드바가 위쪽 가로 막대로 바뀜
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import Icon, { type IconName } from "../../components/Icon";
import { cx, initialOf } from "../../components/ui";
import { inquiryApi } from "../../services/api";

function MenuLink({ to, icon, label, count, end }: { to: string; icon: IconName; label: string; count?: number | null; end?: boolean }) {
  return (
    <NavLink to={to} end={end}
      className={({ isActive }) => cx("flex shrink-0 items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2 text-sm transition",
        isActive ? "bg-primary font-semibold text-white shadow-sm shadow-primary/25"
          : "text-body hover:bg-white/60")}>
      <Icon name={icon} className="h-[18px] w-[18px]" />
      <span className="flex-1">{label}</span>
      {!!count && <span className="rounded-full bg-primary-soft px-2 py-px text-xs font-semibold tabular-nums text-primary">{count}</span>}
    </NavLink>
  );
}

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [openCount, setOpenCount] = useState<number | null>(null);
  const isAdmin = user?.role === "admin";

  // 미처리 건수 (상담원은 자기에게 배정된 문의만 집계됨). 화면을 옮길 때마다 새로 셈
  useEffect(() => {
    inquiryApi.list({ open: "true", size: 1 }).then((r) => setOpenCount(r.total)).catch(() => setOpenCount(null));
  }, [pathname]);

  const initial = initialOf(user?.display_name ?? "");

  return (
    <div className="min-h-screen lg:pl-64">
      <aside className="border-b border-white/60 bg-white/45 backdrop-blur lg:fixed lg:inset-y-0 lg:left-0 lg:flex lg:w-64 lg:flex-col lg:border-b-0 lg:border-r lg:border-white/60">
        <div className="flex items-center justify-between gap-2 px-4 py-3 lg:px-5 lg:py-5">
          <span className="flex items-center gap-2 font-semibold text-ink">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-pink text-sm font-bold text-white" aria-hidden>Q</span>
            InquAI 관리
          </span>
        </div>

        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 [scrollbar-width:none] lg:flex-1 lg:flex-col lg:overflow-visible lg:pb-0">
          <p className="hidden px-3 pb-1 pt-2 text-xs font-semibold tracking-wider text-muted lg:block">업무</p>
          {isAdmin && <MenuLink to="/admin" end icon="dashboard" label="대시보드" />}
          <MenuLink to="/admin/inquiries" icon="inbox" label="문의 관리" count={openCount} />
          <p className="hidden px-3 pb-1 pt-5 text-xs font-semibold tracking-wider text-muted lg:block">설정</p>
          {isAdmin && <MenuLink to="/admin/users" icon="users" label="계정 관리" />}
          <MenuLink to="/admin/account" icon="lock" label="내 계정" />
        </nav>

      </aside>

      {/* 오른쪽 위: 로그인한 사람 (누르면 내 계정) + 로그아웃 */}
      <div className="mx-auto flex max-w-7xl justify-end px-4 pt-4 lg:px-8 lg:pt-6">
        <div className="flex items-center gap-1 rounded-2xl border border-white/70 bg-white/70 p-1 shadow-sm shadow-primary/5 backdrop-blur">
          <NavLink to="/admin/account" title="내 계정 · 비밀번호 변경"
            className="flex items-center gap-2.5 rounded-xl py-1 pl-1 pr-3 hover:bg-white">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-white" aria-hidden>
              {initial}
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-semibold text-ink">{user?.display_name}</span>
              <span className="block text-xs text-muted">{isAdmin ? "관리자" : "상담원"} · {user?.username}</span>
            </span>
          </NavLink>
          <span className="h-6 w-px bg-hairline" aria-hidden />
          <button className="flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm text-body hover:bg-white hover:text-ink"
            onClick={async () => { await logout(); navigate("/login", { replace: true }); }}>
            <Icon name="logout" />
            <span className="hidden sm:inline">로그아웃</span>
          </button>
        </div>
      </div>

      <main className="mx-auto max-w-7xl px-4 pb-6 pt-2 lg:px-8 lg:pb-8">
        <Outlet />
      </main>
    </div>
  );
}
