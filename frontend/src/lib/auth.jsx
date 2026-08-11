import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react';
import { api, setOnUnauthorized } from './api';
import { useGoogleAuthActions } from './auth/googleActions';
import { useAppleAuthActions } from './auth/appleActions';
import { useOtpAuthActions } from './auth/otpActions';

const AuthCtx = createContext(null);

/**
 * Root AuthProvider — owns {user, loading} state + core email/password
 * actions (signup, login, logout, refresh). External-provider action
 * surfaces (Google, Apple, OTP) live in `./auth/*Actions.js` as
 * dedicated hooks, all wired into the context here.
 *
 * 2026-08-11 — P2 Tier-2 split: extracted 3 provider hooks. Zero
 * behaviour change; context surface (all callback names + shapes) is
 * unchanged. Consumers of `useAuth()` see the same object as before.
 */
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

  const { googleStart, googleExchange, googleCompleteSignup } = useGoogleAuthActions(setUser);
  const { appleStart, appleCompleteSignup } = useAppleAuthActions(setUser);
  const { otpStatus, otpStart, otpVerify } = useOtpAuthActions(setUser);

  const value = useMemo(() => ({
    user, loading, signup, login, logout, refresh,
    googleStart, googleExchange, googleCompleteSignup,
    appleStart, appleCompleteSignup,
    otpStatus, otpStart, otpVerify,
  }), [user, loading, signup, login, logout, refresh,
       googleStart, googleExchange, googleCompleteSignup,
       appleStart, appleCompleteSignup,
       otpStatus, otpStart, otpVerify]);
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth() {
  const v = useContext(AuthCtx);
  if (!v) throw new Error('useAuth outside <AuthProvider>');
  return v;
}
