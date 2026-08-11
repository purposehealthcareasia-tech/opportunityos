import { useCallback } from 'react';
import { api } from '../api';

/**
 * Apple Sign-In (standards-based OIDC) action hook.
 *
 * Backend returns 503 { error: "apple_auth_not_configured" } when
 * Apple Developer credentials are absent — the UI uses this to render
 * an honest disabled state instead of a broken button.
 *
 * Split from `src/lib/auth.jsx` on 2026-08-11 (P2 Tier-2). Zero
 * behaviour change.
 */
export function useAppleAuthActions(setUser) {
  const appleStart = useCallback(async () => {
    const { data } = await api.get('/api/v1/auth/apple/start');
    if (data && data.authorize_url) {
      window.location.href = data.authorize_url;
    }
    return data;
  }, []);

  const appleCompleteSignup = useCallback(async ({ pending_signup_id, consents, policy_text_version }) => {
    const { data } = await api.post('/api/v1/auth/apple/complete', {
      pending_signup_id, consents, policy_text_version,
    });
    setUser(data.user);
    return data;
  }, [setUser]);

  return { appleStart, appleCompleteSignup };
}
