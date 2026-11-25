// 관리자 화면 틀: 왼쪽 사이드바(메뉴 + 미처리 건수) / 위쪽 문의 검색 · 알림 · 로그인한 사람·로그아웃 / 본문
// 세 영역(사이드바 / 위쪽 검색·내 정보 / 본문)을 각각 둥근 판으로 나눠 구역이 한눈에 보이게 (2026-11-19)
// 좁은 화면(lg 미만)에서는 사이드바가 위쪽 가로 막대로 바뀜
import { Suspense, useEffect, useRef, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";

import { useAuth } from "../../auth/AuthProvider";
import Icon, { type IconName } from "../../components/Icon";
import NotificationBell from "../../components/NotificationBell";
import { Spinner, cx, initialOf } from "../../components/ui";
import { inquiryApi, opsApi } from "../../services/api";

function MenuLink({ to, icon, label, count, end }: { to: string; icon: IconName; label: string; count?: number | null; end?: boolean }) {
  return (
    <NavLink to={to} end={end}
      // 선택된 메뉴: 꽉 찬 파란 버튼 대신 흰 바탕 + 왼쪽 파란 막대 (오래 봐도 눈이 덜 피곤하게). 좁은 화면(가로 메뉴)은 막대 대신 바탕만
      className={({ isActive }) => cx("relative flex shrink-0 items-center gap-2.5 whitespace-nowrap rounded-xl px-3 py-2 text-sm transition",
        isActive ? "bg-white font-semibold text-primary shadow-sm shadow-primary/10 lg:before:absolute lg:before:inset-y-1.5 lg:before:-left-3 lg:before:w-1 lg:before:rounded-r-full lg:before:bg-primary"
          : "text-body hover:bg-white/60")}>
      <Icon name={icon} className="h-[18px] w-[18px]" />
      <span className="flex-1">{label}</span>
      {!!count && <span className="rounded-full bg-primary-soft px-2 py-px text-xs font-semibold tabular-nums text-primary">{count}</span>}
    </NavLink>
  );
}

/** 메뉴 묶음 제목 (업무 / 쇼핑몰 정보 / 설정): 넓은 화면에서만, 위에 가는 구분선 + 진한 글씨로 묶음이 한눈에 보이게 */
function MenuTitle({ children, first }: { children: string; first?: boolean }) {
  return (
    <p className={cx("hidden px-3 pb-1.5 text-[13px] font-bold text-ink lg:block", first ? "pt-1" : "mt-3 border-t border-hairline pt-4")}>
      {children}
    </p>
  );
}

/** 어느 화면에서나 문의 찾기 (문의 번호·이메일·제목·내용). '/' 키로 바로 입력.
 *  하나만 찾아지면 그 문의 상세로, 여러 건이면 문의 목록에서 결과를 보여 줌 */
function GlobalSearch() {
  const navigate = useNavigate();
  const box = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || t.closest("input, textarea, select, [contenteditable=true]")) return;
      e.preventDefault();
      box.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const word = q.trim();
    if (!word) return;
    setBusy(true);
    try {
      const r = await inquiryApi.list({ q: word, size: 2 });
      navigate(r.total === 1 ? `/admin/inquiries/${r.items[0].id}` : `/admin/inquiries?q=${encodeURIComponent(word)}`);
    } catch {
      navigate(`/admin/inquiries?q=${encodeURIComponent(word)}`);
    } finally {
      setBusy(false);
      setQ("");
      box.current?.blur();
    }
  }

  return (
    <form onSubmit={submit} role="search" className="relative min-w-0 flex-1 sm:max-w-md">
      <Icon name="search" className="pointer-events-none absolute left-4 top-1/2 z-10 h-[18px] w-[18px] -translate-y-1/2 text-muted" />
      <input ref={box} value={q} onChange={(e) => setQ(e.target.value)} disabled={busy} maxLength={100}
        placeholder="문의 번호·이메일·제목·고객 이름·주문번호로 찾기" aria-label="문의 검색"
        className="h-12 w-full rounded-2xl border border-hairline bg-white pl-11 pr-12 text-sm text-ink outline-none placeholder:text-muted focus:border-primary" />
      <kbd className="pointer-events-none absolute right-4 top-1/2 z-10 -translate-y-1/2 rounded-md border border-hairline bg-surface-soft px-1.5 font-sans text-xs text-muted">/</kbd>
    </form>
  );
}

export default function AdminLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [openCount, setOpenCount] = useState<number | null>(null);
  const [ticketCount, setTicketCount] = useState<number | null>(null);
  const isAdmin = user?.role === "admin";

  // 미처리 건수 (상담원은 자기에게 배정된 문의만 집계됨). 화면을 옮길 때마다 새로 셈
  useEffect(() => {
    inquiryApi.list({ open: "true", size: 1 }).then((r) => setOpenCount(r.total)).catch(() => setOpenCount(null));
    // 승인 대기 중인 취소·교환·반품 요청 (상담원은 내가 맡은 문의의 것만)
    opsApi.tickets({ status: "접수" }).then((r) => setTicketCount(r.counts["접수"] ?? 0)).catch(() => setTicketCount(null));
  }, [pathname]);

  const initial = initialOf(user?.display_name ?? "");

  return (
    <div className="min-h-screen p-3 lg:py-4 lg:pl-[18rem] lg:pr-4">
      <aside className="mb-3 rounded-2xl border border-white/70 bg-white/60 shadow-sm shadow-primary/5 backdrop-blur lg:fixed lg:bottom-4 lg:left-4 lg:top-4 lg:mb-0 lg:flex lg:w-64 lg:flex-col lg:rounded-3xl">
        <div className="flex items-center justify-between gap-2 px-4 py-3 lg:px-5 lg:py-5">
          <span className="flex items-center gap-2 font-semibold text-ink">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-brand-pink text-sm font-bold text-white" aria-hidden>Q</span>
            InquAI 관리
          </span>
        </div>

        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 [scrollbar-width:none] lg:min-h-0 lg:flex-1 lg:flex-col lg:overflow-y-auto lg:pb-0">
          {/* 자주 쓰는 순서: 상담 업무(매일) → 쇼핑몰 정보(상담 중 찾아보기) → AI 관리(점검) → 설정(가끔) */}
          <MenuTitle first>상담 업무</MenuTitle>
          {isAdmin && <MenuLink to="/admin" end icon="dashboard" label="대시보드" />}
          <MenuLink to="/admin/inquiries" icon="inbox" label="문의 관리" count={openCount} />
          <MenuLink to="/admin/tickets" icon="ticket" label="취소·교환·반품" count={ticketCount} />
          <MenuTitle>쇼핑몰 정보 (조회 전용)</MenuTitle>
          <MenuLink to="/admin/orders" icon="truck" label="주문·배송" />
          <MenuLink to="/admin/customers" icon="person" label="고객 조회" />
          <MenuLink to="/admin/inventory" icon="box" label="재고 현황" />
          <MenuTitle>AI 관리</MenuTitle>
          <MenuLink to="/admin/agent-logs" icon="bot" label="AI 실행 로그" />
          {isAdmin && <MenuLink to="/admin/drafts" icon="edit" label="AI 초안 분석" />}
          {isAdmin && <MenuLink to="/admin/retraining" icon="zap" label="재학습 현황" />}
          <MenuTitle>설정</MenuTitle>
          {isAdmin && <MenuLink to="/admin/faqs" icon="book" label="FAQ 관리" />}
          {isAdmin && <MenuLink to="/admin/templates" icon="message" label="답변 문구" />}
          {isAdmin && <MenuLink to="/admin/users" icon="users" label="계정 관리" />}
          {isAdmin && <MenuLink to="/admin/audit" icon="eye" label="작업 기록" />}
          <MenuLink to="/admin/account" icon="lock" label="내 계정" />
          {/* 고객이 보는 화면 (시연 쇼핑몰 고객센터)을 새 탭으로 */}
          <a href="/faq" target="_blank" rel="noopener"
            className="flex shrink-0 items-center gap-3 whitespace-nowrap rounded-xl px-3 py-2 text-sm text-muted hover:bg-white hover:text-ink lg:mt-auto lg:mb-4">
            <Icon name="external" className="h-[18px] w-[18px]" />고객센터 화면 열기
          </a>
        </nav>

      </aside>

      <div className="mx-auto max-w-[96rem]">
      {/* 위쪽 판: 문의 검색 · 알림 · 로그인한 사람 (누르면 내 계정) + 로그아웃.
          스크롤해도 화면 위에 고정 (판 위의 여백 띠도 바탕색으로 칠해 아래 글이 비치지 않게) */}
      <div className="page-bg sticky top-0 z-20 -mt-3 py-3 lg:-mt-4 lg:py-4">
      <header className="flex items-center justify-between gap-3 rounded-2xl border border-white/70 bg-white/80 p-2 shadow-sm shadow-primary/5 backdrop-blur lg:rounded-3xl lg:px-3">
        <GlobalSearch />
        <div className="flex shrink-0 items-center gap-1">
          <span className="mr-2"><NotificationBell /></span>
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
      </header>
      </div>

      {/* 본문 판: 연한 흰 판 안에 흰 카드들 */}
      <main className="min-h-[calc(100vh-7.5rem)] rounded-2xl border border-white/70 bg-white/35 p-4 shadow-sm shadow-primary/5 lg:rounded-3xl lg:p-6">
        {/* 관리 화면은 나눠서 불러옴 (App.tsx lazy): 처음 여는 화면이면 잠깐 기다림 표시 */}
        <Suspense fallback={<p className="p-6 text-center text-muted"><Spinner /></p>}>
          <Outlet />
        </Suspense>
      </main>
      </div>
    </div>
  );
}
