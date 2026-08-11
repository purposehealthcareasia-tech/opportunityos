import { useCallback } from 'react';
import { api } from '../api';

/**
 * Phone one-time code login (Twilio Verify) action hook.
 *
 * Split from `src/lib/auth.jsx` on 2026-08-11 (P2 Tier-2). Zero
 * behaviour change — same endpoints, same setUser side-effect on
 * 'logged_in'.
 */
export function useOtpAuthActions(setUser) {
  const otpStatus = useCallback(async () => {
    const { data } = await api.get('/api/v1/auth/otp/status');
    return data;
  }, []);

  const otpStart = useCallback(async (phone) => {
    const { data } = await api.post('/api/v1/auth/otp/start', { phone });
    return data;
  }, []);

  const otpVerify = useCallback(async ({ phone, code }) => {
    const { data } = await api.post('/api/v1/auth/otp/verify', { phone, code });
    if (data.status === 'logged_in') setUser(data.user);
    return data;
  }, [setUser]);

  return { otpStatus, otpStart, otpVerify };
}
