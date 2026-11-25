// 알림 종 (관리 화면 오른쪽 위, 이름 앞): 새 알림 수(빨간 숫자) + 누르면 최근 알림 목록
// - 30초마다, 그리고 화면을 옮길 때마다 다시 불러옴 (실시간 연결 없이 단순하게)
// - 목록을 열면 모두 읽음으로 저장 (계정에 저장 → 다른 PC에서도 이어짐). 이번에 연 목록에서는 새 알림을 계속 강조
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router";

import { notificationApi, type NotificationItem } from "../services/api";
import Icon from "./Icon";
import { cx } from "./ui";

const POLL_MS = 30_000;

const KIND: Record<NotificationItem["kind"], { label: string; dot: string }> = {
  assigned: { label: "배정", dot: "bg-primary" },
  followup: { label: "추가 문의", dot: "bg-sky-500" },
  due_soon: { label: "기한 임박", dot: "bg-amber-500" },
  overdue: { label: "기한 초과", dot: "bg-rose-600" },
  bad_rating: { label: "👎 평가", dot: "bg-rose-500" },
  recheck: { label: "다시 안내", dot: "bg-blue-500" },
  memo: { label: "상담원 공유 메모", dot: "bg-amber-500" },
};

function ago(iso: string) {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (min < 1) return "방금";
  if (min < 60) return `${min}분 전`;
  if (min < 60 * 24) return `${Math.floor(min / 60)}시간 전`;
  return `${Math.floor(min / 60 / 24)}일 전`;
}

export default function NotificationBell() {
  const { pathname } = useLocation();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    notificationApi.list().then((r) => { setItems(r.items); setUnread(r.unread); }).catch(() => { /* 다음 주기에 다시 */ });
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);
  useEffect(() => { load(); setOpen(false); }, [pathname, load]);

  // 바깥을 누르거나 Esc 로 닫기
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open]);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && unread > 0) {
      setUnread(0);   // 숫자는 바로 지우고, 목록의 강조(unread)는 이번에 열어 둔 동안 유지
      notificationApi.seen().catch(() => { /* 다음에 다시 열면 됨 */ });
    }
  }

  return (
    <div ref={box} className="relative">
      <button type="button" onClick={toggle} aria-expanded={open} aria-label={unread ? `알림 ${unread}건` : "알림"}
        className="relative flex h-11 w-11 items-center justify-center rounded-full border border-hairline bg-white text-ink hover:border-primary hover:text-primary">
        <Icon name="bell" className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-rose-600 px-1 text-xs font-bold tabular-nums text-white ring-2 ring-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-2 w-[22rem] overflow-hidden rounded-2xl border border-hairline bg-white shadow-xl shadow-primary/10" role="dialog" aria-label="알림">
          <p className="border-b border-hairline px-4 py-3 text-base font-semibold text-ink">알림 <span className="text-sm font-normal text-muted">· 최근 7일</span></p>
          {items.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted">새로 확인할 일이 없어요.</p>
          ) : (
            <ul className="max-h-[26rem] divide-y divide-hairline overflow-y-auto">
              {items.map((n, i) => (
                <li key={`${n.kind}-${n.inquiry_id}-${n.at}-${i}`}>
                  <Link to={`/admin/inquiries/${n.inquiry_id}`} onClick={() => setOpen(false)}
                    className={cx("flex gap-3 px-4 py-3 hover:bg-surface-soft", n.unread && "bg-primary-soft/50")}>
                    <span className={cx("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", KIND[n.kind].dot)} aria-hidden />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center justify-between gap-2 text-xs text-muted">
                        <span className="font-semibold text-body">{KIND[n.kind].label}</span>
                        <span>{ago(n.at)}</span>
                      </span>
                      <span className="block truncate text-sm font-medium text-ink">{n.title}</span>
                      <span className="block truncate text-sm text-muted">{n.text}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
