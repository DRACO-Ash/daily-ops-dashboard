import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { AUTH_TOKEN_KEY } from "../api/client";

interface AuthContextValue {
  isAuthenticated: boolean;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(
    () => localStorage.getItem(AUTH_TOKEN_KEY),
  );

  useEffect(() => {
    if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
    else localStorage.removeItem(AUTH_TOKEN_KEY);
  }, [token]);

  // Stub login: accepts any non-empty username. Replace with real
  // /api/v1/auth/login call once the backend auth endpoint lands.
  async function login(username: string, _password: string) {
    if (!username.trim()) throw new Error("Username is required.");
    setToken("dev-token");
  }

  function logout() {
    setToken(null);
  }

  return (
    <AuthContext.Provider
      value={{ isAuthenticated: !!token, token, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider.");
  return ctx;
}
