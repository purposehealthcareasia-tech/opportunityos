import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react';
import { api, setOnUnauthorized } from './api';

const AuthCtx = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const { data } = await api.get('/api/v1/auth/me');
      setUser(data);
      return data;
    } catch (e) {
      setUser(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setOnUnauthorized(() => setUser(null));
    refresh();
  }, [refresh]);

  const signup = useCallback(async ({ email, password, name, consents, policy_text_version }) => {
    const { data } = await api.post('/api/v1/auth/signup', {
      email, password, name, consents, policy_text_version,
    });
    setUser(data.user);
    return data.user;
  }, []);

  const login = useCallback(async ({ email, password }) => {
    const { data } = await api.post('/api/v1/auth/login', { email, password });
    setUser(data.user);
    return data.user;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post('/api/v1/auth/logout', {});
    } catch (e) { /* best-effort */ }
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, loading, signup, login, logout, refresh }),
                        [user, loading, signup, login, logout, refresh]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const v = useContext(AuthCtx);
  if (!v) throw new Error('useAuth outside <AuthProvider>');
  return v;
}
