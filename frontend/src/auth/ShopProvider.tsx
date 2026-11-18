// 고객 로그인 상태 (쇼핑몰 연동 시연). 관리자 로그인(AuthProvider)과 완전히 따로입니다.
// 실제 서비스에서는 쇼핑몰이 로그인을 맡고, 고객센터는 로그인한 고객 정보를 넘겨받습니다.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { shopApi } from "../services/api";
import type { ShopCustomer } from "../services/types";

interface ShopState {
  customer: ShopCustomer | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<ShopCustomer>;
  logout: () => Promise<void>;
}

const ShopContext = createContext<ShopState | null>(null);

export function ShopProvider({ children }: { children: ReactNode }) {
  const [customer, setCustomer] = useState<ShopCustomer | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    shopApi.me().then(setCustomer).catch(() => setCustomer(null)).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const c = await shopApi.login(email, password);
    setCustomer(c);
    return c;
  }, []);

  const logout = useCallback(async () => {
    try {
      await shopApi.logout();
    } catch {
      // 서버 로그아웃이 실패해도 화면은 로그아웃 상태로
    }
    setCustomer(null);
  }, []);

  const value = useMemo(() => ({ customer, loading, login, logout }), [customer, loading, login, logout]);
  return <ShopContext.Provider value={value}>{children}</ShopContext.Provider>;
}

export function useShop(): ShopState {
  const ctx = useContext(ShopContext);
  if (!ctx) throw new Error("useShop 은 ShopProvider 안에서 써야 합니다.");
  return ctx;
}
