import React, { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import Input from '../components/ui/Input';
import Button from '../components/ui/Button';
import Checkbox from '../components/ui/Checkbox';
import ThemeToggle from '../components/ThemeToggle';
import { useAuth } from '../lib/auth';
import { api } from '../lib/api';
import { CONSENT_SCOPES_FALLBACK, POLICY_TEXT_VERSION_FALLBACK } from '../lib/consentScopes';

export default function Signup() {
  const nav = useNavigate();
  const { signup } = useAuth();
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
        if (Array.isArray(data.scopes)) setScopes(data.scopes);
        if (data.policy_text_version) setPolicyVersion(data.policy_text_version);
      } catch { /* keep fallback */ }
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
    <div className="min-h-screen bg-surface-muted dark:bg-surface-dark">
      <header className="px-6 md:px-10 py-5 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 no-underline text-ink dark:text-ink-dark">
          <ArrowLeft className="h-4 w-4" /> <span className="text-sm">Back to home</span>
        </Link>
        <ThemeToggle />
      </header>

      <main className="px-6 md:px-10 pb-16">
        <div className="max-w-2xl mx-auto">
          <h1 className="text-2xl md:text-3xl font-semibold mb-2">Create your OpportunityOS account</h1>
          <p className="muted mb-8 text-sm max-w-lg">
            You control what OpportunityOS is allowed to do on your behalf. Each scope below is a promise we make about how your data is used — not a marketing checkbox. Only the required scope is needed to create the account.
          </p>

          <form onSubmit={handleSubmit} className="card p-6 md:p-8 space-y-6">
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
            By creating an account, you agree that OpportunityOS will act as a candidate-fiduciary. We will never auto-submit an application without your explicit approval, and we will never invent facts about you.
          </p>
        </div>
      </main>
    </div>
  );
}
