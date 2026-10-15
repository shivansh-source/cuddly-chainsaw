import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, loadSession, saveSession, setToken } from "./api";
import type { Company, Session } from "./types";

interface AuthValue {
  session: Session | null;
  login: (email: string, password: string) => Promise<Session>;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(loadSession);

  const logout = useCallback(() => {
    setToken(null);
    saveSession(null);
    setSession(null);
  }, []);

  useEffect(() => {
    const onUnauthorized = () => logout();
    window.addEventListener("negotiator:unauthorized", onUnauthorized);
    return () => window.removeEventListener("negotiator:unauthorized", onUnauthorized);
  }, [logout]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login(email.trim().toLowerCase(), password);
    setToken(res.access_token);
    const me = await api.me();
    const next: Session = {
      token: res.access_token, role: res.role, company_id: res.company_id,
      email: me.email, company_name: me.company_name,
    };
    saveSession(next);
    setSession(next);
    return next;
  }, []);

  return <AuthContext.Provider value={{ session, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

// Company directory, fetched once per session and shared.
let companyCache: Promise<Company[]> | null = null;

export function useCompanies(): { list: Company[]; name: (id: string) => string; byId: Record<string, Company> } {
  const [list, setList] = useState<Company[]>([]);
  const { session } = useAuth();
  useEffect(() => {
    if (!session) return;
    companyCache ??= api.companies().catch((e) => {
      companyCache = null;
      throw e;
    });
    let alive = true;
    companyCache.then((c) => alive && setList(c)).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [session]);
  const byId = Object.fromEntries(list.map((c) => [c.id, c]));
  return { list, byId, name: (id: string) => byId[id]?.name ?? id };
}

export function resetCompanyCache(): void {
  companyCache = null;
}
