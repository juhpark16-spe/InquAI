// 화면 경로 (기획서 8장). AI 실행 로그 화면은 4주차에 추가합니다.
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router";

import { AuthProvider, useAuth } from "./auth/AuthProvider";
import AccountPage from "./pages/admin/AccountPage";
import AdminLayout from "./pages/admin/AdminLayout";
import FaqsPage from "./pages/admin/FaqsPage";
import InquiryDetailPage from "./pages/admin/InquiryDetailPage";
import InquiryListPage from "./pages/admin/InquiryListPage";
import LoginPage from "./pages/admin/LoginPage";
import UsersPage from "./pages/admin/UsersPage";
import CustomerLayout from "./pages/customer/CustomerLayout";
import FaqPage from "./pages/customer/FaqPage";
import InquiryFormPage from "./pages/customer/InquiryFormPage";
import InquiryLookupPage from "./pages/customer/InquiryLookupPage";
import ProtectedRoute from "./routes/ProtectedRoute";

// 대시보드는 차트 라이브러리(Recharts)가 커서, 고객 화면이 이 코드를 받지 않도록 필요할 때만 불러옴
const DashboardPage = lazy(() => import("./pages/admin/DashboardPage"));

// 첫 화면: 관리자는 대시보드, 상담원은 자기에게 배정된 문의 목록 (통계는 관리자만, 기획서 6장)
function AdminHome() {
  const { user } = useAuth();
  if (user?.role !== "admin") return <Navigate to="/admin/inquiries?open=true" replace />;
  return (
    <Suspense fallback={<p className="p-6 text-center text-slate-500">불러오는 중…</p>}>
      <DashboardPage />
    </Suspense>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* 고객 화면: 로그인 없음 */}
        <Route element={<CustomerLayout />}>
          <Route path="/faq" element={<FaqPage />} />
          <Route path="/inquiry" element={<InquiryFormPage />} />
          <Route path="/inquiry/lookup" element={<InquiryLookupPage />} />
        </Route>

        {/* 관리 화면: 로그인 상태가 필요한 곳에서만 확인 */}
        <Route element={<AuthProvider><Outlet /></AuthProvider>}>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<AdminLayout />}>
              <Route path="/admin" element={<AdminHome />} />
              <Route path="/admin/inquiries" element={<InquiryListPage />} />
              <Route path="/admin/inquiries/:id" element={<InquiryDetailPage />} />
              <Route path="/admin/account" element={<AccountPage />} />
              <Route element={<ProtectedRoute roles={["admin"]} />}>
                <Route path="/admin/users" element={<UsersPage />} />
                <Route path="/admin/faqs" element={<FaqsPage />} />
              </Route>
            </Route>
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/inquiry" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
