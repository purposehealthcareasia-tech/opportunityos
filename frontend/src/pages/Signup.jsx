import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Input from '../components/ui/Input';
import Button from '../components/ui/Button';
import Checkbox from '../components/ui/Checkbox';
import ThemeToggle from '../components/ThemeToggle';
import { useAuth } from '../lib/auth';
import { api } from '../lib/api';
import { CONSENT_SCOPES_FALLBACK, POLICY_TEXT_VERSION_FALLBACK, rebrandScopeCatalog } from '../lib/consentScopes';

function GoogleGlyph() {
  return (
    <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.14-3.09-.4-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
    </svg>
  );
}

export default function Signup() {
  const nav = useNavigate();
  const { signup, googleStart } = useAuth();
  const [scopes, setScopes] = useState(CONSENT_SCOPES_FALLBACK);
  const [policyVersion, setPolicyVersion] = useState(POLICY_TEXT_VERSION_FALLBACK);
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [consents, setConsents] = useState({}); // starts EMPTY. Nothing pre-checked.
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [showPolicyGate, setShowPolicyGate] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get('/api/v1/meta/policy');
        if (cancelled) return;
        if (Array.isArray(data.scopes)) setScopes(rebrandScopeCatalog(data.scopes));
        if (data.policy_text_version) setPolicyVersion(data.policy_text_version);
      } catch (e) { console.debug('policy fetch failed, using fallback', e); }
    })();
    return () => { cancelled = true; };
  }, []);

  const requiredScopes = useMemo(() => scopes.filter((s) => s.required).map((s) => s.scope), [scopes]);
  const canSubmit = useMemo(() => {
    if (!form.name.trim() || !form.email.trim() || form.password.length < 8) return false;
    return requiredScopes.every((s) => consents[s]);
  }, [form, consents, requiredScopes]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    // Build the full consents map explicitly so backend records every scope decision, granted or not.
    const payload = scopes.reduce((acc, s) => ({ ...acc, [s.scope]: !!consents[s.scope] }), {});
    if (!requiredScopes.every((s) => payload[s])) {
      setShowPolicyGate(true);
      return;
    }
    setSubmitting(true);
    try {
      await signup({
        email: form.email.trim().toLowerCase(),
        password: form.password,
        name: form.name.trim(),
        consents: payload,
        policy_text_version: policyVersion,
      });
      nav('/passport', { replace: true });
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (typeof detail === 'string') setError(detail);
      else if (detail?.error === 'required_consent_missing') setError(`Consent to "${detail.scope}" is required to create an account.`);
      else setError('Could not create your account. Please check your details and try again.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen">
      <header className="px-6 md:px-10 py-5 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 no-underline text-ink dark:text-ink-dark">
          <ArrowLeft className="h-4 w-4" /> <span className="text-sm">Back to home</span>
        </Link>
        <ThemeToggle />
      </header>

      <main className="px-6 md:px-10 pb-16">
        <div className="max-w-2xl mx-auto">
          <h1 className="text-2xl md:text-3xl font-semibold mb-2">Create your Fynd account</h1>
          <p className="muted mb-8 text-sm max-w-lg">
            You control what Fynd is allowed to do on your behalf. Each scope below is a promise we make about how your data is used — not a marketing checkbox. Only the required scope is needed to create the account.
          </p>

          <form onSubmit={handleSubmit} className="card p-6 md:p-8 space-y-6">
            <button
              type="button"
              onClick={googleStart}
              data-testid="google-signup-btn"
              className="w-full inline-flex items-center justify-center gap-2 rounded-md border border-line dark:border-line-dark bg-white dark:bg-neutral-900 hover:bg-neutral-50 dark:hover:bg-neutral-800 py-2 text-sm font-medium text-ink dark:text-ink-dark"
            >
              <GoogleGlyph /> Continue with Google
            </button>
            <div className="relative">
              <div className="absolute inset-0 flex items-center"><div className="w-full border-t border-line dark:border-line-dark" /></div>
              <div className="relative text-center"><span className="bg-white dark:bg-bg-dark px-3 text-[10px] uppercase tracking-wider muted">or sign up with email</span></div>
            </div>
            <div className="grid md:grid-cols-2 gap-4">
              <Input
                label="Full name"
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="e.g. Ujjwal Singla"
                autoComplete="name"
              />
              <Input
                label="Email"
                required
                type="email"
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                placeholder="you@work.com"
                autoComplete="email"
              />
            </div>
            <Input
              label="Password"
              required
              type="password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              placeholder="At least 8 characters"
              hint="At least 8 characters. Choose something you don't use anywhere else."
              autoComplete="new-password"
            />

            <div>
              <div className="flex items-baseline justify-between mb-3">
                <h2 className="text-sm font-semibold">Consent scopes</h2>
                <span className="text-xs muted">Policy v{policyVersion}</span>
              </div>
              <p className="text-xs muted mb-4">
                None are pre-checked. Uncheck any time in Settings; revoking a scope makes dependent features stop working, with a clear explanation.
              </p>
              <div className="space-y-4">
                {scopes.map((s) => (
                  <Checkbox
                    key={s.scope}
                    checked={!!consents[s.scope]}
                    onChange={(v) => setConsents((c) => ({ ...c, [s.scope]: v }))}
                    label={s.label}
                    description={s.description}
                    required={s.required}
                  />
                ))}
              </div>
              {showPolicyGate && (
                <p className="text-xs text-red-600 dark:text-red-400 mt-3">
                  You must accept the required scope ({requiredScopes.join(', ')}) to create an account.
                </p>
              )}
            </div>

            {error && (
              <div className="rounded-md border border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-300 text-sm px-3 py-2">
                {error}
              </div>
            )}

            <div className="flex items-center justify-between pt-2">
              <p className="text-xs muted">Already have an account? <Link to="/login" className="font-medium">Sign in</Link>.</p>
              <Button type="submit" disabled={!canSubmit} loading={submitting}>
                {submitting ? 'Creating account…' : 'Create account'}
              </Button>
            </div>
          </form>

          <p className="text-xs muted mt-6 max-w-lg">
            By creating an account, you agree that Fynd will act as a candidate-fiduciary. We will never auto-submit an application without your explicit approval, and we will never invent facts about you.
          </p>
        </div>
      </main>
    </div>
  );
}
