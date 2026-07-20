import React, { useEffect, useState } from 'react';
import Card, { CardHeader } from '../components/ui/Card';
import { api } from '../lib/api';
import { Loader2, ShieldAlert } from 'lucide-react';

export default function Admin() {
  const [flags, setFlags] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await api.get('/api/v1/admin/feature-flags');
        if (!cancelled) setFlags(data.flags || []);
      } catch (e) {
        if (!cancelled) setError('Could not load feature flags.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-fadeIn">
      <div className="flex items-center gap-2">
        <ShieldAlert className="h-5 w-5 text-accent" />
        <h1 className="text-2xl font-semibold">Admin</h1>
        <span className="pill pill-neutral">Phase 1 preview</span>
      </div>
      <p className="muted text-sm max-w-xl">
        The full admin console — role assignment, audit trail viewer, feature-flag mutations, sample-job badges — lands in <span className="font-medium text-ink dark:text-ink-dark">phase 6</span>. This surface exists today to prove role-gating and to expose a read view of feature flags.
      </p>
      <Card>
        <CardHeader title="Feature flags" subtitle="Read-only in Phase 1. Mutations arrive with the full admin console." />
        {loading ? (
          <div className="flex items-center gap-2 muted text-sm py-4"><Loader2 className="h-4 w-4 animate-spin"/> Loading…</div>
        ) : error ? (
          <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        ) : flags.length === 0 ? (
          <p className="text-sm muted">No flags yet.</p>
        ) : (
          <div className="divide-y divide-line dark:divide-line-dark">
            {flags.map((f) => (
              <div key={f.key} className="py-3 flex items-center justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-sm font-mono">{f.key}</div>
                  <div className="text-xs muted">changed by {f.changed_by || 'system'}</div>
                </div>
                <span className={f.value ? 'pill pill-accent' : 'pill pill-neutral'}>
                  {String(f.value)}
                </span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
