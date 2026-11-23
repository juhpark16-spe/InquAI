import { NavLink, Outlet, useNavigate } from "react-router";

import { ShopProvider, useShop } from "../../auth/ShopProvider";
import { cx } from "../../components/ui";

// 쇼핑몰 로그인 상태 (오른쪽 위): 로그인하지 않았으면 '비회원' + [로그인] 버튼,
// 로그인했으면 이름 원형 + 'OO님' + [내 쇼핑] 버튼(파랑) + 로그아웃. 문의하기·문의 조회의 로그인 안내 줄 대신 여기서 보여 줌
function ShopMenu() {
  const { customer, logout } = useShop();
  const navigate = useNavigate();
  if (!customer) {
    return (
      <span className="flex items-center gap-2 text-sm">
        <span className="hidden whitespace-nowrap text-muted sm:inline">비회원</span>
        <NavLink to="/shop/login" className="whitespace-nowrap rounded-full border border-primary/40 bg-white px-4 py-1.5 font-semibold text-primary hover:bg-primary-soft">
          로그인
        </NavLink>
      </span>
    );
  }
  return (
    <span className="flex items-center gap-2 text-sm">
      <span className="flex items-center gap-1.5" title={customer.email}>
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-sm font-bold text-white" aria-hidden>{customer.name.slice(0, 1)}</span>
        <span className="whitespace-nowrap font-semibold text-ink">{customer.name}님</span>
      </span>
      <NavLink to="/my" className={({ isActive }) => cx("whitespace-nowrap rounded-full px-4 py-1.5 font-semibold",
        isActive ? "bg-primary text-white shadow-sm shadow-primary/25" : "border border-primary/40 bg-white text-primary hover:bg-primary-soft")}>내 쇼핑</NavLink>
      <button className="whitespace-nowrap rounded-full px-2 py-1.5 text-muted hover:text-ink"
        onClick={async () => { navigate("/inquiry"); await logout(); }}>로그아웃</button>
    </span>
  );
}

export default function CustomerLayout() {
  return <ShopProvider><CustomerShell /></ShopProvider>;
}

function CustomerShell() {
  const link = ({ isActive }: { isActive: boolean }) =>
    cx("whitespace-nowrap rounded-full px-3 sm:px-4 py-2 text-sm font-medium", isActive ? "bg-primary text-white shadow-sm shadow-primary/25" : "text-muted hover:bg-white/60 hover:text-ink");
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-white/60 bg-white/55 backdrop-blur">
        <div className="mx-auto flex min-h-16 max-w-3xl flex-wrap items-center justify-between gap-2 px-4 py-2">
          <span className="flex items-center gap-2 font-semibold text-ink"><span className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-pink text-sm font-bold text-white" aria-hidden>Q</span>InquAI 고객센터</span>
          <nav className="flex gap-1">
            <NavLink to="/faq" className={link}>자주 묻는 질문</NavLink>
            <NavLink to="/inquiry" end className={link}>문의하기</NavLink>
            <NavLink to="/inquiry/lookup" className={link}>문의 조회</NavLink>
          </nav>
          <ShopMenu />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-8">
        <Outlet />
      </main>
      <footer className="mt-16 border-t border-white/60 bg-white/40 py-10 text-center text-sm text-muted">
        <p className="font-semibold text-ink">InquAI 쇼핑 고객센터</p>
        <p className="mt-1">상담 시간 평일 10:00~17:00 · 문의는 24시간 접수</p>
      </footer>
    </div>
  );
}
