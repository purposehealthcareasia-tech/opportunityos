import React, { useCallback, useEffect, useState } from 'react';
import { Lock, Download, Trash2, AlertTriangle, Undo2, Loader2, ShieldCheck } from 'lucide-react';
import { api } from '../lib/api';

/**
 * S20 — Privacy & consent.
 *  - Live scopes with revoke buttons.
 *  - Data-release log (from receipts + authorizations).
 *  - Export JSON (async job → downloadable bundle).
 *  - Staged deletion (30-day soft-delete window with restore).
 */

export default function PrivacyPage() {
  const [scopes, setScopes] = useState([]);
  const [releases, setReleases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [flash, setFlash] = useState(null);
  const [exportJob, setExportJob] = useState(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [c, r] = await Promise.all([
        api.get('/api/v1/privacy/consents'),
        api.get('/api/v1/privacy/release-log'),
      ]);
      setScopes(c.data.scopes || []);
      setReleases(r.data.releases || []);
    } catch (e) { console.debug('privacy load error', e); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const revoke = async (scope) => {
    try {
      await api.post('/api/v1/privacy/consents/revoke', { scope });
      setFlash({ kind: 'ok', message: `Consent revoked for ${scope}.` });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: 'Revoke failed.' });
    }
  };

  const startExport = async () => {
    try {
      const r = await api.post('/api/v1/privacy/export', {});
      setExportJob({ id: r.data.job_id, status: r.data.status });
      // Immediately poll for ready.
      const detail = await api.get(`/api/v1/privacy/export/${r.data.job_id}`);
      if (detail.data.status === 'ready' && detail.data.download) {
        const blob = new Blob([JSON.stringify(detail.data.download.content, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = detail.data.download.filename;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        setFlash({ kind: 'ok', message: `Bundle downloaded (${detail.data.download.filename}).` });
      }
    } catch (e) {
      setFlash({ kind: 'warn', message: 'Export failed.' });
    }
  };

  const confirmDelete = async () => {
    try {
      const r = await api.post('/api/v1/privacy/account/delete', { confirm: true });
      setFlash({ kind: 'warn', message: r.data.message });
      setShowDeleteConfirm(false);
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail?.message || 'Delete failed.' });
    }
  };

  return (
    <div className="space-y-8" data-testid="privacy-page">
      <header className="space-y-1">
        <h1 className="text-3xl sm:text-4xl font-semibold tracking-tight flex items-center gap-2"><Lock className="h-6 w-6" /> Privacy</h1>
        <p className="muted max-w-3xl">Your consents, releases, and a one-click export of everything we have on you.</p>
      </header>

      {flash && (
        <div className={`rounded-md border px-3 py-2 text-sm ${flash.kind === 'ok' ? 'bg-accent/10 border-accent/40 text-accent' : 'bg-amber-50 border-amber-400 text-amber-900 dark:bg-amber-950 dark:text-amber-200'}`} data-testid="privacy-flash">
          {flash.message}
        </div>
      )}

      <section className="space-y-3" data-testid="consent-scopes">
        <h2 className="text-lg font-semibold flex items-center gap-2"><ShieldCheck className="h-4 w-4" /> Active consent scopes</h2>
        {loading ? <Loader2 className="h-4 w-4 animate-spin muted" /> : (
          <ul className="space-y-2">
            {scopes.map((s) => (
              <li key={s.scope} className="rounded-md border border-line dark:border-line-dark p-3 flex items-center justify-between" data-testid={`consent-row-${s.scope}`}>
                <div>
                  <div className="font-medium text-sm">{s.label}</div>
                  <div className="text-xs muted font-mono">{s.scope}</div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`pill text-xs ${s.granted ? 'pill-accent' : 'pill-neutral'}`}>{s.granted ? 'granted' : 'revoked'}</span>
                  {s.granted && (
                    <button type="button" className="text-xs underline muted" onClick={() => revoke(s.scope)} data-testid={`consent-revoke-${s.scope}`}>
                      Revoke
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3" data-testid="release-log">
        <h2 className="text-lg font-semibold">Data-release log</h2>
        {releases.length === 0 ? (
          <p className="muted text-sm">No releases yet — nothing has been sent to an employer via OpportunityOS on your behalf.</p>
        ) : (
          <ul className="space-y-2 text-sm">
            {releases.map((r) => (
              <li key={r.receipt_id} className="rounded-md border border-line dark:border-line-dark p-3">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{r.employer}</span>
                  <span className="text-xs muted">{new Date(r.ts).toLocaleString()}</span>
                </div>
                <div className="text-xs muted">{r.role} · req <span className="font-mono">{r.req_ref}</span> · hash <span className="font-mono">{(r.materials_hash || '').slice(0, 10)}</span></div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3" data-testid="export-section">
        <h2 className="text-lg font-semibold flex items-center gap-2"><Download className="h-4 w-4" /> Export</h2>
        <p className="text-sm muted">A complete JSON bundle: profile, claims (including your own sealed values), documents, resumes, preferences, eligibility, applications, receipts, outcomes, interviews, consents, screener answers, subscriptions, and your audit trail.</p>
        <button type="button" className="btn-primary text-sm" onClick={startExport} data-testid="export-btn">
          <Download className="h-4 w-4" /> Export my data
        </button>
      </section>

      <section className="space-y-3" data-testid="delete-section">
        <h2 className="text-lg font-semibold text-red-600 dark:text-red-400 flex items-center gap-2"><Trash2 className="h-4 w-4" /> Delete account</h2>
        <p className="text-sm muted">Enters a 30-day soft-delete window. Sign in during that window to restore. After 30 days, all your data is permanently removed.</p>
        {!showDeleteConfirm ? (
          <button type="button" className="text-sm underline text-red-600 dark:text-red-400" onClick={() => setShowDeleteConfirm(true)} data-testid="delete-open">
            Delete my account…
          </button>
        ) : (
          <div className="rounded-md border border-red-400 bg-red-50 dark:bg-red-950 dark:text-red-200 text-red-900 p-3 space-y-2" data-testid="delete-confirm">
            <div className="flex items-start gap-2"><AlertTriangle className="h-4 w-4 mt-0.5" /> This starts the 30-day countdown.</div>
            <div className="flex items-center gap-2">
              <button type="button" className="btn-primary text-sm bg-red-600 hover:bg-red-700 text-white" onClick={confirmDelete} data-testid="delete-confirm-btn">
                Yes, start 30-day deletion
              </button>
              <button type="button" className="text-sm underline muted" onClick={() => setShowDeleteConfirm(false)}>
                <Undo2 className="h-3 w-3 inline mr-1" /> Cancel
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
