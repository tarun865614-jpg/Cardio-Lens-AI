import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";
import { completeLogin, logoutUrl, startLogin, type AuthConfig } from "./oidc";
import type { Role, User } from "./types";

interface AuthState {
  user: User | null;
  loading: boolean;
  config: AuthConfig | null;
  login: (email: string, password: string) => Promise<void>;
  loginSso: (returnTo?: string) => Promise<void>;
  finishSso: (search: string) => Promise<string>;
  logout: () => void;
  can: (...roles: Role[]) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [config, setConfig] = useState<AuthConfig | null>(null);

  useEffect(() => {
    setUnauthorizedHandler(() => setUser(null));
    const cfg = api.get<AuthConfig>("/auth/config").catch(() => ({ mode: "local" }) as AuthConfig);
    const me = getToken() ? api.get<User>("/auth/me").catch(() => (setToken(null), null)) : Promise.resolve(null);
    Promise.all([cfg, me])
      .then(([c, u]) => {
        setConfig(c);
        setUser(u);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api.post<{ access_token: string; user: User }>("/auth/login", { email, password });
    setToken(r.access_token);
    setUser(r.user);
  }, []);

  const loginSso = useCallback(async (returnTo = "/") => {
    if (config?.mode !== "oidc") throw new Error("Single sign-on is not configured");
    await startLogin(config, returnTo);
  }, [config]);

  const finishSso = useCallback(
    async (search: string) => {
      if (config?.mode !== "oidc") throw new Error("Single sign-on is not configured");
      const { accessToken, returnTo } = await completeLogin(config, search);
      setToken(accessToken);
      try {
        setUser(await api.get<User>("/auth/me")); // API verifies the token, MFA and role
      } catch (e) {
        setToken(null);
        throw e;
      }
      return returnTo;
    },
    [config],
  );

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    if (config?.mode === "oidc") logoutUrl(config).then((u) => u && window.location.assign(u));
  }, [config]);

  const can = useCallback((...roles: Role[]) => !!user && roles.includes(user.role), [user]);

  return <Ctx.Provider value={{ user, loading, config, login, loginSso, finishSso, logout, can }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export const CLINICAL: Role[] = ["clinician", "admin"];
export const RESEARCH: Role[] = ["researcher", "admin"];
export const ADMIN: Role[] = ["admin"];

export function homeFor(role: Role): string {
  return role === "researcher" ? "/research" : "/";
}
