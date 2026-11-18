// 로그인하지 않았으면 로그인 화면으로 보냅니다. (화면 편의일 뿐, 실제 권한 검사는 FastAPI가 함)
import { Navigate, Outlet, useLocation } from "react-router";

import { useAuth } from "../auth/AuthProvider";
import type { Role } from "../services/types";

export default function ProtectedRoute({ roles }: { roles?: Role[] }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <p className="p-8 text-slate-500">확인 중…</p>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  // 임시 비밀번호로 로그인했으면 새 비밀번호를 정하기 전까지 다른 화면으로 가지 못함 (서버도 다른 API를 403으로 막음)
  if (user.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace state={{ from: location.pathname + location.search }} />;
  }
  if (roles && !roles.includes(user.role)) return <Navigate to="/admin/inquiries" replace />;
  return <Outlet />;
}
