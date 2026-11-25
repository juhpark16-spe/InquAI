// 화면 경로 (기획서 8장)
import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router";

import { AuthProvider, useAuth } from "./auth/AuthProvider";
import ConfirmHost from "./components/ConfirmDialog";
import AdminLayout from "./pages/admin/AdminLayout";
import ChangePasswordPage from "./pages/admin/ChangePasswordPage";
import LoginPage from "./pages/admin/LoginPage";
import CustomerLayout from "./pages/customer/CustomerLayout";
import FaqPage from "./pages/customer/FaqPage";
import InquiryFormPage from "./pages/customer/InquiryFormPage";
import InquiryLookupPage from "./pages/customer/InquiryLookupPage";
import MyPage from "./pages/customer/MyPage";
import ShopLoginPage from "./pages/customer/ShopLoginPage";
import ProtectedRoute from "./routes/ProtectedRoute";

// 대시보드는 차트 라이브러리(Recharts)가 커서, 고객 화면이 이 코드를 받지 않도록 필요할 때만 불러옴
const DashboardPage = lazy(() => import("./pages/admin/DashboardPage"));
// 관리 화면들도 필요할 때만 불러옴: 고객 화면(첫 방문)이 관리 화면 코드를 받지 않게 (AdminLayout 의 Suspense 가 기다림 표시)
const AccountPage = lazy(() => import("./pages/admin/AccountPage"));
const AgentLogsPage = lazy(() => import("./pages/admin/AgentLogsPage"));
const AuditLogPage = lazy(() => import("./pages/admin/AuditLogPage"));
const FaqsPage = lazy(() => import("./pages/admin/FaqsPage"));
const RetrainingPage = lazy(() => import("./pages/admin/RetrainingPage"));
const TemplatesPage = lazy(() => import("./pages/admin/TemplatesPage"));
const DraftQualityPage = lazy(() => import("./pages/admin/DraftQualityPage"));
const InquiryDetailPage = lazy(() => import("./pages/admin/InquiryDetailPage"));
const InquiryListPage = lazy(() => import("./pages/admin/InquiryListPage"));
const UsersPage = lazy(() => import("./pages/admin/UsersPage"));
const TicketsPage = lazy(() => import("./pages/admin/TicketsPage"));
const CustomersPage = lazy(() => import("./pages/admin/CustomersPage"));
const InventoryPage = lazy(() => import("./pages/admin/InventoryPage"));
const OrdersPage = lazy(() => import("./pages/admin/OrdersPage"));

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
          <Route path="/shop/login" element={<ShopLoginPage />} />
          <Route path="/my" element={<MyPage />} />
        </Route>

        {/* 관리 화면: 로그인 상태가 필요한 곳에서만 확인 */}
        <Route element={<AuthProvider><Outlet /></AuthProvider>}>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/change-password" element={<ChangePasswordPage />} />
            <Route element={<AdminLayout />}>
              <Route path="/admin" element={<AdminHome />} />
              <Route path="/admin/inquiries" element={<InquiryListPage />} />
              <Route path="/admin/inquiries/:id" element={<InquiryDetailPage />} />
              <Route path="/admin/agent-logs" element={<AgentLogsPage />} />
              <Route path="/admin/tickets" element={<TicketsPage />} />
              <Route path="/admin/customers" element={<CustomersPage />} />
              <Route path="/admin/customers/:id" element={<CustomersPage />} />
              <Route path="/admin/orders" element={<OrdersPage />} />
              <Route path="/admin/inventory" element={<InventoryPage />} />
              <Route path="/admin/account" element={<AccountPage />} />
              <Route element={<ProtectedRoute roles={["admin"]} />}>
                <Route path="/admin/users" element={<UsersPage />} />
                <Route path="/admin/faqs" element={<FaqsPage />} />
                <Route path="/admin/retraining" element={<RetrainingPage />} />
                <Route path="/admin/drafts" element={<DraftQualityPage />} />
                <Route path="/admin/templates" element={<TemplatesPage />} />
                <Route path="/admin/audit" element={<AuditLogPage />} />
              </Route>
            </Route>
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/inquiry" replace />} />
      </Routes>
      <ConfirmHost />
    </BrowserRouter>
  );
}
