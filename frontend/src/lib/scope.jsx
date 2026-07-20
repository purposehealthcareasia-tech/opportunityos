import React, { useCallback, useState } from 'react';
import { ShieldOff, ShieldCheck, Loader2 } from 'lucide-react';
import { api } from './api';
import Button from '../components/ui/Button';

export function isConsentError(err) {
  const detail = err?.response?.data?.detail;
  return detail && detail.error === 'consent_required';
}

export function consentErrorScope(err) {
  return err?.response?.data?.detail?.scope || null;
}

/**
 * Inline scope-required prompt. Renders a card explaining which consent is needed and lets the user
 * grant it directly. When granted, calls onGranted so the parent can refetch.
 */
export function ScopeRequiredPrompt({ scope, description, onGranted }) {
  const [granting, setGranting] = useState(false);
  const [error, setError] = useState('');
  const grant = useCallback(async () => {
    setGranting(true); setError('');
    try {
      await api.post('/api/v1/consents', { scope, granted: true, policy_text_version: '1.0' });
      onGranted?.();
    } catch (e) {
      setError('Could not grant this scope. Please try again.');
    } finally {
      setGranting(false);
    }
  }, [scope, onGranted]);
  return (
    <div className="card p-6">
      <div className="flex items-start gap-3">
        <div className="h-10 w-10 rounded-md border border-line dark:border-line-dark grid place-items-center">
          <ShieldOff className="h-4 w-4 text-accent" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">This feature is off until you grant the <span className="font-mono">{scope}</span> scope</h3>
          <p className="text-sm muted mt-1 leading-relaxed max-w-lg">
            {description || 'OpportunityOS only turns on features once you\'ve explicitly consented to them. Revoke later in Settings whenever you want.'}
          </p>
          {error && <p className="text-xs text-red-600 dark:text-red-400 mt-2">{error}</p>}
          <div className="mt-4 flex items-center gap-2">
            <Button variant="accent" onClick={grant} loading={granting}>
              <ShieldCheck className="h-3.5 w-3.5" /> Grant {scope}
            </Button>
            <span className="text-xs muted">You can revoke at any time from Settings.</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function LoadingBlock({ label = 'Loading…' }) {
  return (
    <div className="flex items-center gap-2 muted text-sm py-6 justify-center">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function ErrorBlock({ message, onRetry }) {
  return (
    <div className="rounded-md border border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-300 text-sm px-4 py-3 flex items-center justify-between gap-3">
      <span>{message}</span>
      {onRetry && <button type="button" onClick={onRetry} className="underline text-xs">Retry</button>}
    </div>
  );
}

export function EmptyBlock({ title, hint, action }) {
  return (
    <div className="rounded-card border border-dashed border-line dark:border-line-dark p-8 text-center">
      <h4 className="text-sm font-semibold">{title}</h4>
      {hint && <p className="text-sm muted mt-1 max-w-lg mx-auto">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
