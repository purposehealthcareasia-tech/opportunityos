import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import Button from '../components/ui/Button';
import Checkbox from '../components/ui/Checkbox';
import ThemeToggle from '../components/ThemeToggle';
import { useAuth } from '../lib/auth';
import { api } from '../lib/api';
import { CONSENT_SCOPES_FALLBACK, POLICY_TEXT_VERSION_FALLBACK, rebrandScopeCatalog } from '../lib/consentScopes';

/**
 * Google Sign-In callback — receives `#session_id=<sid>` from the Emergent
 * OAuth redirect, exchanges it with the backend, and either logs the user in
 * OR renders the consent-first signup form for a new account.
 *
 * REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS,
 * THIS BREAKS THE AUTH.
 */
export default function GoogleCallback() {
  const nav = useNavigate();
  const { googleExchange, googleCompleteSignup } = useAuth();
  const [phase, setPhase] = useState('checking'); // checking | pending | done | error
  const [pending, setPending] = useState(null); // { pending_signup_id, email, name, picture }
  const [error, setError] = useState('');
  const [scopes, setScopes] = useState(CONSENT_SCOPES_FALLBACK);
  const [policyVersion, setPolicyVersion] = useState(POLICY_TEXT_VERSION_FALLBACK);
  const [consents, setConsents] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const processed = useRef(false);

  const requiredScopes = useMemo(
    () => scopes.filter((s) => s.required).map((s) => s.scope), [scopes],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get('/api/v1/meta/policy');
        if (cancelled) return;
        if (Array.isArray(data.scopes)) setScopes(rebrandScopeCatalog(data.scopes));
        if (data.policy_text_version) setPolicyVersion(data.policy_text_version);
      } catch (e) { /* fallback is fine */ }
    })();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    // Extract session_id from fragment or query.
    const hash = window.location.hash || '';
    const search = window.location.search || '';
    const sid =
      new URLSearchParams(hash.startsWith('#') ? hash.substring(1) : hash).get('session_id') ||
      new URLSearchParams(search.startsWith('?') ? search.substring(1) : search).get('session_id');

    // Clean the URL so the fragment is not persisted.
    if (sid) {
      window.history.replaceState(null, '', window.location.pathname);
    }

    if (!sid) {
      setPhase('error');
      setError('Missing session id. Please retry sign-in.');
      return;
    }

    (async () => {
      try {
        const result = await googleExchange(sid);
        if (result.status === 'logged_in') {
          setPhase('done');
          nav('/settings', { replace: true });
          return;
        }
        if (result.status === 'pending_consent') {
          setPending(result);
          setPhase('pending');
          return;
        }
        setPhase('error');
        setError('Unexpected response from server.');
      } catch (e) {
        setPhase('error');
        setError(e?.response?.data?.detail?.message
          || 'Google sign-in failed. Please try again.');
      }
    })();
  }, [googleExchange, nav]);

  async function handleSubmitConsent(e) {
    e.preventDefault();
    setError('');
    const payload = scopes.reduce((acc, s) => ({ ...acc, [s.scope]: !!consents[s.scope] }), {});
    for (const s of requiredScopes) {
      if (!payload[s]) {
        setError('You must accept the required consents to continue.');
        return;
      }
    }
    setSubmitting(true);
    try {
      await googleCompleteSignup({
        pending_signup_id: pending.pending_signup_id,
        consents: payload,
        policy_text_version: policyVersion,
      });
      nav('/passport', { replace: true });
    } catch (err) {
      setError(err?.response?.data?.detail?.message || 'Failed to complete signup.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen bg-surface-muted dark:bg-surface-dark" data-testid="google-callback">
      <header className="px-6 md:px-10 py-5 flex items-center justify-between">
        <span className="text-sm muted">Google sign-in</span>
        <ThemeToggle />
      </header>
      <main className="px-6 md:px-10 pb-16">
        <div className="max-w-md mx-auto pt-10">
          {phase === 'checking' && (
            <div className="flex items-center gap-3 text-sm muted" data-testid="google-checking">
              <Loader2 className="h-4 w-4 animate-spin" />
              Verifying Google session…
            </div>
          )}
          {phase === 'error' && (
            <div className="card p-6 space-y-4" data-testid="google-error">
              <h1 className="text-xl font-semibold">Sign-in couldn't finish</h1>
              <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
              <Button onClick={() => nav('/login')}>Return to login</Button>
            </div>
          )}
          {phase === 'pending' && pending && (
            <form onSubmit={handleSubmitConsent} className="card p-6 space-y-5" data-testid="google-consent-form">
              <div>
                <h1 className="text-xl font-semibold">Finish creating your account</h1>
                <p className="text-sm muted mt-1">
                  Signed in as <span className="font-medium">{pending.email}</span>. Choose which
                  scopes we may act under before we create your account.
                </p>
              </div>
              <ul className="space-y-3">
                {scopes.map((s) => (
                  <li key={s.scope} className="flex items-start gap-3">
                    <Checkbox
                      id={`scope-${s.scope}`}
                      checked={!!consents[s.scope]}
                      onChange={(checked) => setConsents((c) => ({ ...c, [s.scope]: checked }))}
                      data-testid={`google-consent-${s.scope}`}
                    />
                    <label htmlFor={`scope-${s.scope}`} className="text-sm">
                      <div className="font-medium">
                        {s.title || s.scope}
                        {s.required && <span className="ml-1 text-red-500">*</span>}
                      </div>
                      {s.description && <p className="muted text-xs">{s.description}</p>}
                    </label>
                  </li>
                ))}
              </ul>
              {error && (
                <div className="rounded-md border border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-300 text-sm px-3 py-2">
                  {error}
                </div>
              )}
              <div className="flex items-center justify-between">
                <p className="text-xs muted">Policy version {policyVersion}</p>
                <Button type="submit" loading={submitting} data-testid="google-consent-submit">
                  Create account
                </Button>
              </div>
            </form>
          )}
        </div>
      </main>
    </div>
  );
}
