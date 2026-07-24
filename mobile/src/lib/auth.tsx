import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react';
import { api, setOnUnauthorized } from './api';
import { hydrateTokens, captureSessionFromResponse, clearTokens } from './session';

interface User {
  id: string;
  email: string;
  name: string;
  role: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  signup: (params: {
    email: string;
    password: string;
    name: string;
    consents: Record<string, boolean>;
    policy_text_version: string;
  }) => Promise<User>;
  login: (params: { email: string; password: string }) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<User | null>;
}

const AuthCtx = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/auth/me');
      setUser(data);
      return data;
    } catch {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  /* Boot: hydrate tokens from secure-store then validate session */
  useEffect(() => {
    setOnUnauthorized(() => {
      clearTokens();
      setUser(null);
    });
    (async () => {
      await hydrateTokens();
      await refresh();
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const signup = useCallback(async ({ email, password, name, consents, policy_text_version }: any) => {
    const response = await api.post('/api/v1/auth/signup', {
      email, password, name, consents, policy_text_version,
    });
    await captureSessionFromResponse(response);
    setUser(response.data.user);
    return response.data.user;
  }, []);

  const login = useCallback(async ({ email, password }: { email: string; password: string }) => {
    const response = await api.post('/api/v1/auth/login', { email, password });
    await captureSessionFromResponse(response);
    setUser(response.data.user);
    return response.data.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post('/api/v1/auth/logout', {});
    } catch { /* ignore — clearing client state is sufficient */ }
    await clearTokens();
    setUser(null);
  }, []);

  const value = useMemo(() => ({
    user, loading, signup, login, logout, refresh,
  }), [user, loading, signup, login, logout, refresh]);

  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const v = useContext(AuthCtx);
  if (!v) throw new Error('useAuth outside <AuthProvider>');
  return v;
}
