import { useCallback } from 'react';
import { api } from '../api';

/**
 * Google Sign-In (Emergent-managed) action hook.
 *
 * REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT
 * URLS, THIS BREAKS THE AUTH. redirect_url comes from
 * window.location.origin.
 *
 * Split from `src/lib/auth.jsx` on 2026-08-11 (P2 Tier-2). Zero
 * behaviour change — same API endpoints, same URL construction, same
 * setUser side-effect on 'logged_in'.
 */
export function useGoogleAuthActions(setUser) {
  const googleStart = useCallback(() => {
    const redirectUrl = window.location.origin + '/auth/callback';
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  }, []);

  const googleExchange = useCallback(async (sessionId) => {
    const { data } = await api.post('/api/v1/auth/google/session', { session_id: sessionId });
    if (data.status === 'logged_in') {
      setUser(data.user);
    }
    return data;
  }, [setUser]);

  const googleCompleteSignup = useCallback(async ({ pending_signup_id, consents, policy_text_version }) => {
    const { data } = await api.post('/api/v1/auth/google/complete', {
      pending_signup_id, consents, policy_text_version,
    });
    setUser(data.user);
    return data;
  }, [setUser]);

  return { googleStart, googleExchange, googleCompleteSignup };
}
