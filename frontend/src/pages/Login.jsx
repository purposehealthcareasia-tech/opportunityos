import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { ArrowLeft, Phone, KeySquare, Apple } from 'lucide-react';
import Input from '../components/ui/Input';
import Button from '../components/ui/Button';
import ThemeToggle from '../components/ThemeToggle';
import { useAuth } from '../lib/auth';

// Inline Google glyph — 20px, brand-accurate, no external asset.
function GoogleGlyph({ className = '' }) {
  return (
    <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden className={className}>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.14-3.09-.4-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
      <path fill="none" d="M0 0h48v48H0z"/>
    </svg>
  );
}

export default function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const { login, googleStart, appleStart, otpStatus, otpStart, otpVerify } = useAuth();
  const [form, setForm] = useState({ email: '', password: '' });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  // Truthful configuration probes for optional providers.
  const [otpCfg, setOtpCfg] = useState({ configured: null }); // null=loading
  const [appleCfg, setAppleCfg] = useState({ configured: null });
  const [mode, setMode] = useState('email'); // 'email' | 'phone'
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const [phoneStage, setPhoneStage] = useState('start'); // 'start' | 'verify'
  const [phoneStatus, setPhoneStatus] = useState('');
  const [phoneBusy, setPhoneBusy] = useState(false);
  const [appleBusy, setAppleBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try { setOtpCfg(await otpStatus()); } catch { setOtpCfg({ configured: false }); }
    })();
    // Cheap probe — call /apple/start; a 503 → not configured.
    (async () => {
      try {
        const r = await fetch(`${process.env.REACT_APP_BACKEND_URL}/api/v1/auth/apple/start`, {
          credentials: 'include',
        });
        setAppleCfg({ configured: r.status === 200 });
      } catch { setAppleCfg({ configured: false }); }
    })();
  }, [otpStatus]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login({ email: form.email.trim().toLowerCase(), password: form.password });
      const redirect = loc.state?.from && loc.state.from !== '/login' ? loc.state.from : '/settings';
      nav(redirect, { replace: true });
    } catch (err) {
      setError('Email or password not recognized.');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAppleStart() {
    setAppleBusy(true);
    try { await appleStart(); }
    catch { setError('Sign in with Apple is not available right now.'); }
    finally { setAppleBusy(false); }
  }

  async function handlePhoneStart(e) {
    e.preventDefault();
    setPhoneStatus(''); setError(''); setPhoneBusy(true);
    try {
      await otpStart(phone);
      setPhoneStage('verify');
      setPhoneStatus('Code sent. Enter the 6-digit code we texted you.');
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(detail?.message || detail?.error || 'Could not send code.');
    } finally { setPhoneBusy(false); }
  }

  async function handlePhoneVerify(e) {
    e.preventDefault();
    setError(''); setPhoneBusy(true);
    try {
      const res = await otpVerify({ phone, code });
      if (res.status === 'logged_in') {
        const redirect = loc.state?.from && loc.state.from !== '/login' ? loc.state.from : '/settings';
        nav(redirect, { replace: true });
      }
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setError(detail?.message || detail?.error || 'Code is incorrect.');
    } finally { setPhoneBusy(false); }
  }

  const isAppleConfigured  = appleCfg.configured === true;
  const isOtpConfigured    = otpCfg.configured === true;

  return (
    <div className="min-h-screen bg-surface-muted dark:bg-surface-dark">
      <header className="px-6 md:px-10 py-5 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 no-underline text-ink dark:text-ink-dark">
          <ArrowLeft className="h-4 w-4" /> <span className="text-sm">Back to home</span>
        </Link>
        <ThemeToggle />
      </header>
      <main className="px-6 md:px-10 pb-16">
        <div className="max-w-md mx-auto pt-10">
          <h1 className="text-2xl font-semibold mb-2">Sign in</h1>
          <p className="muted text-sm mb-8">Welcome back. Pick the sign-in method you registered with.</p>

          <div className="card p-6 space-y-4">
            <button
              type="button"
              onClick={googleStart}
              data-testid="google-signin-btn"
              className="w-full inline-flex items-center justify-center gap-2 rounded-md border border-line dark:border-line-dark bg-white dark:bg-neutral-900 hover:bg-neutral-50 dark:hover:bg-neutral-800 py-2 text-sm font-medium text-ink dark:text-ink-dark"
            >
              <GoogleGlyph /> Continue with Google
            </button>

            <button
              type="button"
              onClick={handleAppleStart}
              disabled={!isAppleConfigured || appleBusy}
              data-testid="apple-signin-btn"
              title={isAppleConfigured
                ? 'Sign in with Apple'
                : 'Sign in with Apple is not yet configured on this server.'}
              className={`w-full inline-flex items-center justify-center gap-2 rounded-md border py-2 text-sm font-medium ${
                isAppleConfigured
                  ? 'border-black bg-black text-white hover:bg-neutral-900'
                  : 'border-line dark:border-line-dark bg-neutral-100 dark:bg-neutral-800 text-neutral-500 cursor-not-allowed'
              }`}
            >
              <Apple className="h-4 w-4" />
              {isAppleConfigured ? 'Continue with Apple' : 'Continue with Apple — not yet available'}
            </button>

            <div className="grid grid-cols-2 gap-2 pt-2">
              <button
                type="button"
                data-testid="login-mode-email"
                onClick={() => { setMode('email'); setPhoneStage('start'); setError(''); }}
                className={`text-xs py-1.5 rounded-md border ${
                  mode === 'email'
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-line dark:border-line-dark muted'
                }`}
              >Email &amp; password</button>
              <button
                type="button"
                data-testid="login-mode-phone"
                onClick={() => { setMode('phone'); setError(''); }}
                className={`text-xs py-1.5 rounded-md border inline-flex items-center justify-center gap-1 ${
                  mode === 'phone'
                    ? 'border-accent bg-accent/10 text-accent'
                    : 'border-line dark:border-line-dark muted'
                }`}
              ><Phone className="h-3 w-3" /> Phone one-time code</button>
            </div>

            {mode === 'email' && (
              <form onSubmit={handleSubmit} className="space-y-5 pt-2" data-testid="login-form-email">
                <Input
                  label="Email"
                  type="email"
                  required
                  autoComplete="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                />
                <Input
                  label="Password"
                  type="password"
                  required
                  autoComplete="current-password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                />
                {error && (
                  <div data-testid="login-error-message" className="rounded-md border border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-300 text-sm px-3 py-2">
                    {error}
                  </div>
                )}
                <div className="flex items-center justify-between">
                  <p className="text-xs muted">No account? <Link to="/signup" className="font-medium">Create one</Link>.</p>
                  <Button type="submit" data-testid="login-submit-btn" loading={submitting}>Sign in</Button>
                </div>
              </form>
            )}

            {mode === 'phone' && (
              <div className="space-y-4 pt-2" data-testid="login-form-phone">
                {otpCfg.configured === null && (
                  <div className="text-xs muted">Checking availability…</div>
                )}
                {isOtpConfigured === false && (
                  <div data-testid="otp-unavailable" className="rounded-md border border-amber-500/30 bg-amber-500/5 text-amber-700 dark:text-amber-300 text-xs px-3 py-2">
                    Phone sign-in is not yet configured on this server. Use email or Google/Apple sign-in for now.
                  </div>
                )}
                {isOtpConfigured && phoneStage === 'start' && (
                  <form onSubmit={handlePhoneStart} className="space-y-4">
                    <Input
                      label="Phone (E.164, e.g. +14155552671)"
                      type="tel"
                      required
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      data-testid="otp-phone-input"
                    />
                    {error && (
                      <div data-testid="otp-error-message" className="rounded-md border border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-300 text-xs px-3 py-2">{error}</div>
                    )}
                    <div className="flex items-center justify-between">
                      <p className="text-xs muted">You'll get an SMS with a 6-digit code.</p>
                      <Button type="submit" loading={phoneBusy} data-testid="otp-start-btn">
                        <Phone className="h-3.5 w-3.5 mr-1" /> Send code
                      </Button>
                    </div>
                  </form>
                )}
                {isOtpConfigured && phoneStage === 'verify' && (
                  <form onSubmit={handlePhoneVerify} className="space-y-4">
                    <div className="text-xs muted">{phoneStatus}</div>
                    <Input
                      label="6-digit code"
                      type="text"
                      inputMode="numeric"
                      pattern="\d{4,10}"
                      required
                      value={code}
                      onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                      data-testid="otp-code-input"
                    />
                    {error && (
                      <div data-testid="otp-error-message" className="rounded-md border border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-300 text-xs px-3 py-2">{error}</div>
                    )}
                    <div className="flex items-center justify-between">
                      <button
                        type="button"
                        onClick={() => { setPhoneStage('start'); setCode(''); }}
                        className="text-xs muted underline"
                        data-testid="otp-back-btn"
                      >Back</button>
                      <Button type="submit" loading={phoneBusy} data-testid="otp-verify-btn">
                        <KeySquare className="h-3.5 w-3.5 mr-1" /> Sign in
                      </Button>
                    </div>
                  </form>
                )}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
