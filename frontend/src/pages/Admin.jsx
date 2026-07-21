import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ShieldAlert, Search, RefreshCw, Users, CreditCard, Inbox, ToggleLeft, LifeBuoy, Activity, AlertTriangle, Loader2, X, Check, Lock, Cable } from 'lucide-react';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';

/**
 * S18 — Admin Console (Phase 6).
 *
 * Founder amendment 2 in force:
 *  - Sealed values are masked with NO unmask capability anywhere in v0.1.
 *  - Every user-detail view writes an audit row server-side.
 *  - Refunds require the reason enum + optional note.
 *  - Flag changes are audited.
 *  - Support role = READ-ONLY everywhere except support tickets. Enforced
 *    server-side; UI mirrors that by disabling write buttons.
 */

const TABS = [
  { id: 'users',        label: 'Users',          Icon: Users },
  { id: 'subs',         label: 'Subscriptions',  Icon: CreditCard },
  { id: 'queue',        label: 'Manual queue',   Icon: Inbox },
  { id: 'flags',        label: 'Feature flags',  Icon: ToggleLeft },
  { id: 'integrations', label: 'Integrations',   Icon: Cable },
  { id: 'tickets',      label: 'Support',        Icon: LifeBuoy },
  { id: 'health',       label: 'Health',         Icon: Activity },
  { id: 'obs',          label: 'Observability',  Icon: AlertTriangle },
];

export default function Admin() {
  const { user } = useAuth();
  const [tab, setTab] = useState('users');
  const isAdmin = user?.role === 'admin';

  return (
    <div className="space-y-6" data-testid="admin-console">
      <header className="flex items-center gap-2">
        <ShieldAlert className="h-6 w-6 text-accent" />
        <h1 className="text-2xl font-semibold">Admin Console</h1>
        <span className="pill pill-neutral text-xs uppercase tracking-wide" data-testid="admin-role-badge">
          {user?.role || 'user'}
        </span>
        {!isAdmin && (
          <span className="pill pill-neutral text-xs" data-testid="admin-readonly-badge">
            <Lock className="h-3 w-3 inline mr-1" /> read-only (support role)
          </span>
        )}
      </header>

      <nav className="flex flex-wrap gap-2 border-b border-line dark:border-line-dark pb-2" data-testid="admin-tabs">
        {TABS.map(({ id, label, Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`text-sm px-3 py-1.5 rounded-md inline-flex items-center gap-1.5 ${
              tab === id ? 'bg-accent/10 text-accent border border-accent/40' : 'muted hover:bg-neutral-100 dark:hover:bg-neutral-900'
            }`}
            data-testid={`admin-tab-${id}`}
          >
            <Icon className="h-3.5 w-3.5" /> {label}
          </button>
        ))}
      </nav>

      {tab === 'users'   && <UsersTab isAdmin={isAdmin} />}
      {tab === 'subs'    && <SubscriptionsTab isAdmin={isAdmin} />}
      {tab === 'queue'   && <QueueTab isAdmin={isAdmin} />}
      {tab === 'flags'   && <FlagsTab isAdmin={isAdmin} />}
      {tab === 'integrations' && <IntegrationsTab isAdmin={isAdmin} />}
      {tab === 'tickets' && <TicketsTab />}
      {tab === 'health'  && <HealthTab />}
      {tab === 'obs'     && <ObservabilityTab isAdmin={isAdmin} />}
    </div>
  );
}

// ----------------------------------------------------------------------------
// USERS
// ----------------------------------------------------------------------------
function UsersTab({ isAdmin }) {
  const [q, setQ] = useState('');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get('/api/v1/admin/users', { params: { q } });
      setRows(r.data.users || []);
    } finally { setLoading(false); }
  }, [q]);
  useEffect(() => { load(); }, [load]);

  const openDetail = async (uid) => {
    setDetail({ loading: true, id: uid });
    try {
      const r = await api.get(`/api/v1/admin/users/${uid}`);
      setDetail({ loading: false, id: uid, ...r.data });
    } catch (e) {
      setDetail({ loading: false, id: uid, error: 'Failed to load user' });
    }
  };

  return (
    <section className="space-y-3" data-testid="admin-users-tab">
      <div className="flex items-center gap-2">
        <Search className="h-4 w-4 muted" />
        <input
          type="text"
          placeholder="Search by email or id…"
          className="flex-1 rounded-md border border-line dark:border-line-dark bg-transparent px-3 py-1.5 text-sm"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && load()}
          data-testid="admin-user-search"
        />
        <button type="button" className="pill pill-neutral text-xs" onClick={load}>
          <RefreshCw className="h-3 w-3 inline mr-1" /> Refresh
        </button>
      </div>

      {loading ? <Loader2 className="h-4 w-4 animate-spin muted" /> : (
        <div className="rounded-md border border-line dark:border-line-dark overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-900 text-xs uppercase muted">
              <tr>
                <th className="text-left px-3 py-2">Email</th>
                <th className="text-left px-3 py-2">Role</th>
                <th className="text-left px-3 py-2">Deletion</th>
                <th className="text-left px-3 py-2">Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((u) => (
                <tr key={u.id} className="border-t border-line dark:border-line-dark" data-testid={`admin-user-row-${u.id}`}>
                  <td className="px-3 py-2 font-mono text-xs">{u.email}</td>
                  <td className="px-3 py-2"><span className="pill pill-neutral text-[10px]">{u.role || 'user'}</span></td>
                  <td className="px-3 py-2 text-xs">{u.deletion_pending_at ? <span className="pill text-[10px] bg-red-100 dark:bg-red-950 text-red-700 dark:text-red-300">pending</span> : '—'}</td>
                  <td className="px-3 py-2 text-xs muted">{u.created_at ? new Date(u.created_at).toLocaleDateString() : '—'}</td>
                  <td className="px-3 py-2 text-right">
                    <button type="button" className="text-xs underline text-accent" onClick={() => openDetail(u.id)} data-testid={`admin-user-detail-btn-${u.id}`}>
                      View
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && !loading && (
                <tr><td colSpan={5} className="px-3 py-6 text-center muted text-sm">No users match.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" data-testid="admin-user-detail-modal">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-line dark:border-line-dark bg-bg dark:bg-bg-dark p-5 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">User detail</h3>
              <button type="button" onClick={() => setDetail(null)} data-testid="admin-user-detail-close"><X className="h-4 w-4" /></button>
            </div>
            {detail.loading ? <Loader2 className="h-4 w-4 animate-spin muted" /> : detail.error ? (
              <p className="text-sm text-red-600">{detail.error}</p>
            ) : (
              <div className="space-y-3 text-sm">
                <div className="rounded-md border border-line dark:border-line-dark p-3 space-y-1">
                  <div className="text-xs muted uppercase">Identity</div>
                  <div>{detail.user?.email}</div>
                  <div className="text-xs muted font-mono">{detail.user?.id}</div>
                  <div className="text-xs">Applications: <span className="font-medium">{detail.counts?.applications ?? 0}</span> · Receipts: <span className="font-medium">{detail.counts?.receipts ?? 0}</span></div>
                </div>

                <div className="rounded-md border border-line dark:border-line-dark p-3 space-y-1">
                  <div className="text-xs muted uppercase">Subscription</div>
                  {detail.subscription ? (
                    <div className="text-sm">{detail.subscription.plan?.toUpperCase()} — <span className="muted">status {detail.subscription.status || 'active'}</span></div>
                  ) : <div className="muted text-xs">No subscription (free tier).</div>}
                </div>

                <div className="rounded-md border border-line dark:border-line-dark p-3 space-y-1" data-testid="admin-user-eligibility">
                  <div className="text-xs muted uppercase">Eligibility profile</div>
                  {detail.eligibility_profile ? (
                    <div className="text-xs space-y-0.5">
                      {['status', 'dates', 'notes', 'derived_flags'].map((k) => (
                        detail.eligibility_profile[k] !== undefined && (
                          <div key={k} className="flex items-start gap-2">
                            <span className="muted min-w-[110px]">{k}:</span>
                            <span className="font-mono">
                              {typeof detail.eligibility_profile[k] === 'string'
                                ? detail.eligibility_profile[k]
                                : JSON.stringify(detail.eligibility_profile[k])}
                            </span>
                          </div>
                        )
                      ))}
                      <div className="flex items-start gap-2">
                        <span className="muted min-w-[110px]">sensitivity:</span>
                        <span className={`pill text-[10px] ${detail.eligibility_profile.sensitivity === 'sealed' ? 'pill-neutral' : 'pill-accent'}`}>
                          {detail.eligibility_profile.sensitivity || 'normal'}
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-xs muted">No eligibility profile.</div>
                  )}
                  <p className="text-[10px] muted italic">Sealed values are masked. No unmask path exists in v0.1.</p>
                </div>

                <div className="rounded-md border border-line dark:border-line-dark p-3 space-y-1" data-testid="admin-user-claims">
                  <div className="text-xs muted uppercase">Claims ({detail.claims?.length || 0})</div>
                  {(detail.claims || []).map((c) => {
                    const isSealed = (c.sensitivity || '').toLowerCase() === 'sealed';
                    return (
                      <div key={c.id} className="flex items-start justify-between border-t border-line dark:border-line-dark py-1.5 first:border-0">
                        <div className="text-xs">
                          <span className="pill pill-neutral text-[10px] mr-2">{c.type}</span>
                          <span className="font-mono text-xs">{isSealed ? c.value : (typeof c.value === 'string' ? c.value : JSON.stringify(c.value).slice(0, 60))}</span>
                        </div>
                        <span className={`pill text-[10px] ${c.status === 'approved' ? 'pill-accent' : 'pill-neutral'}`}>{c.status}</span>
                      </div>
                    );
                  })}
                  <p className="text-[10px] muted italic">Sealed values are masked. No unmask path exists in v0.1.</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// SUBSCRIPTIONS + REFUND
// ----------------------------------------------------------------------------
const REFUND_REASONS = [
  'duplicate_charge',
  'customer_request',
  'billing_error',
  'goodwill',
  'policy_bounded_first_purchase',
];

function SubscriptionsTab({ isAdmin }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [refunding, setRefunding] = useState(null);   // sub row
  const [reason, setReason] = useState(REFUND_REASONS[0]);
  const [note, setNote] = useState('');
  const [flash, setFlash] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get('/api/v1/admin/subscriptions');
      setRows(r.data.subscriptions || []);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submitRefund = async () => {
    if (!refunding) return;
    try {
      const r = await api.post(`/api/v1/admin/subscriptions/${refunding.id}/refund`, { reason, note });
      setFlash({ kind: 'ok', message: `Refund recorded (reason=${r.data.reason}).` });
      setRefunding(null); setNote(''); setReason(REFUND_REASONS[0]);
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail?.message || 'Refund failed.' });
    }
  };

  return (
    <section className="space-y-3" data-testid="admin-subs-tab">
      {flash && <FlashBanner {...flash} onDismiss={() => setFlash(null)} />}
      {loading ? <Loader2 className="h-4 w-4 animate-spin muted" /> : (
        <div className="rounded-md border border-line dark:border-line-dark overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-neutral-50 dark:bg-neutral-900 text-xs uppercase muted">
              <tr>
                <th className="text-left px-3 py-2">User</th>
                <th className="text-left px-3 py-2">Plan</th>
                <th className="text-left px-3 py-2">Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.id} className="border-t border-line dark:border-line-dark" data-testid={`admin-sub-row-${s.id}`}>
                  <td className="px-3 py-2 font-mono text-xs">{s.user_id}</td>
                  <td className="px-3 py-2"><span className="pill pill-accent text-[10px]">{s.plan}</span></td>
                  <td className="px-3 py-2 text-xs">{s.status || 'active'}{s.cancel_at_period_end ? ' · cancels' : ''}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      className="text-xs underline text-red-600 disabled:opacity-40 disabled:no-underline"
                      disabled={!isAdmin}
                      onClick={() => setRefunding(s)}
                      data-testid={`admin-refund-open-${s.id}`}
                    >
                      Refund
                    </button>
                  </td>
                </tr>
              ))}
              {rows.length === 0 && !loading && (
                <tr><td colSpan={4} className="px-3 py-6 text-center muted text-sm">No subscriptions.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {refunding && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" data-testid="admin-refund-modal">
          <div className="w-full max-w-md rounded-lg border border-line dark:border-line-dark bg-bg dark:bg-bg-dark p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Issue refund</h3>
              <button type="button" onClick={() => setRefunding(null)}><X className="h-4 w-4" /></button>
            </div>
            <div className="text-xs muted">Subscription: <span className="font-mono">{refunding.id}</span></div>
            <label className="block text-xs">Reason (required)
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                className="mt-1 w-full rounded-md border border-line dark:border-line-dark bg-transparent px-2 py-1.5 text-sm"
                data-testid="admin-refund-reason"
              >
                {REFUND_REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
            </label>
            <label className="block text-xs">Note (optional)
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                className="mt-1 w-full rounded-md border border-line dark:border-line-dark bg-transparent px-2 py-1.5 text-xs"
                data-testid="admin-refund-note"
              />
            </label>
            <button type="button" className="btn-primary text-sm w-full" onClick={submitRefund} data-testid="admin-refund-submit">
              Confirm refund
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// MANUAL QUEUE
// ----------------------------------------------------------------------------
function QueueTab({ isAdmin }) {
  const [rows, setRows] = useState([]);
  const [note, setNote] = useState({});
  const [flash, setFlash] = useState(null);

  const load = useCallback(async () => {
    const r = await api.get('/api/v1/admin/manual-queue');
    setRows(r.data.items || []);
  }, []);
  useEffect(() => { load(); }, [load]);

  const resolve = async (id) => {
    try {
      await api.post(`/api/v1/admin/manual-queue/${id}/resolve`, { note: note[id] || '' });
      setFlash({ kind: 'ok', message: `Item ${id.slice(0, 8)} resolved. User will see updated tracker on next load.` });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail || 'Resolve failed.' });
    }
  };

  return (
    <section className="space-y-3" data-testid="admin-queue-tab">
      {flash && <FlashBanner {...flash} onDismiss={() => setFlash(null)} />}
      {rows.length === 0 ? (
        <p className="muted text-sm">Queue empty. Nothing waiting for manual review.</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((it) => (
            <li key={it.id} className="rounded-md border border-line dark:border-line-dark p-3" data-testid={`admin-queue-row-${it.id}`}>
              <div className="flex items-center justify-between">
                <div className="text-sm">
                  <span className="font-mono text-xs muted">{it.application_id}</span>
                  <span className="ml-3 pill pill-neutral text-[10px]">{it.state}</span>
                </div>
                <span className="text-xs muted">{it.created_at && new Date(it.created_at).toLocaleString()}</span>
              </div>
              <div className="mt-2 flex items-center gap-2">
                <input
                  type="text"
                  value={note[it.id] || ''}
                  onChange={(e) => setNote({ ...note, [it.id]: e.target.value })}
                  placeholder="Resolution note…"
                  className="flex-1 rounded-md border border-line dark:border-line-dark bg-transparent px-2 py-1 text-xs"
                  data-testid={`admin-queue-note-${it.id}`}
                />
                <button
                  type="button"
                  className="pill pill-accent text-xs disabled:opacity-40"
                  disabled={!isAdmin}
                  onClick={() => resolve(it.id)}
                  data-testid={`admin-queue-resolve-${it.id}`}
                >
                  Resolve
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// FEATURE FLAGS
// ----------------------------------------------------------------------------
function FlagsTab({ isAdmin }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [newFlag, setNewFlag] = useState({ name: '', enabled: true, description: '' });
  const [flash, setFlash] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get('/api/v1/admin/flags');
      setRows(r.data.flags || []);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const toggle = async (name, next) => {
    try {
      await api.patch(`/api/v1/admin/flags/${name}`, { enabled: next });
      setFlash({ kind: 'ok', message: `Flag ${name} → ${next}.` });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail || 'Toggle failed.' });
    }
  };

  const create = async () => {
    if (!newFlag.name.trim()) return;
    try {
      await api.post('/api/v1/admin/flags', newFlag);
      setFlash({ kind: 'ok', message: `Flag ${newFlag.name} created.` });
      setNewFlag({ name: '', enabled: true, description: '' });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: e?.response?.data?.detail || 'Create failed.' });
    }
  };

  const remove = async (name) => {
    try {
      await api.delete(`/api/v1/admin/flags/${name}`);
      setFlash({ kind: 'ok', message: `Flag ${name} deleted.` });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: 'Delete failed.' });
    }
  };

  return (
    <section className="space-y-4" data-testid="admin-flags-tab">
      {flash && <FlashBanner {...flash} onDismiss={() => setFlash(null)} />}
      {loading ? <Loader2 className="h-4 w-4 animate-spin muted" /> : (
        <ul className="space-y-2">
          {rows.map((f) => (
            <li key={f.name} className="rounded-md border border-line dark:border-line-dark p-3 flex items-center justify-between" data-testid={`admin-flag-row-${f.name}`}>
              <div>
                <div className="text-sm font-mono">{f.name}</div>
                <div className="text-xs muted">{f.description || '(no description)'} · by {f.created_by || 'system'}</div>
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  disabled={!isAdmin}
                  onClick={() => toggle(f.name, !f.enabled)}
                  className={`pill text-xs disabled:opacity-40 ${f.enabled ? 'pill-accent' : 'pill-neutral'}`}
                  data-testid={`admin-flag-toggle-${f.name}`}
                >
                  {f.enabled ? 'enabled' : 'disabled'}
                </button>
                {isAdmin && (
                  <button type="button" onClick={() => remove(f.name)} className="text-xs muted underline" data-testid={`admin-flag-delete-${f.name}`}>Delete</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {isAdmin && (
        <div className="rounded-md border border-line dark:border-line-dark p-3 space-y-2" data-testid="admin-flag-create">
          <div className="text-xs muted uppercase">Create flag</div>
          <div className="flex gap-2">
            <input type="text" placeholder="name" value={newFlag.name} onChange={(e) => setNewFlag({ ...newFlag, name: e.target.value })} className="rounded-md border border-line dark:border-line-dark bg-transparent px-2 py-1 text-xs flex-1" data-testid="admin-flag-new-name" />
            <input type="text" placeholder="description" value={newFlag.description} onChange={(e) => setNewFlag({ ...newFlag, description: e.target.value })} className="rounded-md border border-line dark:border-line-dark bg-transparent px-2 py-1 text-xs flex-1" />
            <label className="text-xs flex items-center gap-1"><input type="checkbox" checked={newFlag.enabled} onChange={(e) => setNewFlag({ ...newFlag, enabled: e.target.checked })} /> enabled</label>
            <button type="button" className="pill pill-accent text-xs" onClick={create} data-testid="admin-flag-create-btn">Create</button>
          </div>
        </div>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// SUPPORT TICKETS  (support role IS allowed to write here)
// ----------------------------------------------------------------------------
function TicketsTab() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [reply, setReply] = useState({});
  const [flash, setFlash] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get('/api/v1/admin/support-tickets');
      setRows(r.data.tickets || []);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const send = async (id) => {
    const text = (reply[id] || '').trim();
    if (!text) return;
    try {
      await api.post(`/api/v1/admin/support-tickets/${id}/reply`, { reply: text });
      setReply({ ...reply, [id]: '' });
      setFlash({ kind: 'ok', message: 'Reply added.' });
      await load();
    } catch (e) { setFlash({ kind: 'warn', message: 'Reply failed.' }); }
  };
  const close = async (id) => {
    try {
      await api.post(`/api/v1/admin/support-tickets/${id}/close`, {});
      setFlash({ kind: 'ok', message: 'Ticket closed.' });
      await load();
    } catch (e) { setFlash({ kind: 'warn', message: 'Close failed.' }); }
  };

  return (
    <section className="space-y-3" data-testid="admin-tickets-tab">
      {flash && <FlashBanner {...flash} onDismiss={() => setFlash(null)} />}
      {loading ? <Loader2 className="h-4 w-4 animate-spin muted" /> : rows.length === 0 ? (
        <p className="muted text-sm">No tickets yet.</p>
      ) : (
        <ul className="space-y-3">
          {rows.map((t) => (
            <li key={t.id} className="rounded-md border border-line dark:border-line-dark p-3 space-y-2" data-testid={`admin-ticket-${t.id}`}>
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium">{t.subject || '(no subject)'}</div>
                <span className={`pill text-[10px] ${t.status === 'closed' ? 'pill-neutral' : 'pill-accent'}`}>{t.status || 'open'}</span>
              </div>
              <div className="text-xs muted">from <span className="font-mono">{t.user_id}</span></div>
              <div className="text-sm">{t.body}</div>
              {(t.replies || []).map((r, i) => (
                <div key={i} className="rounded-md bg-neutral-50 dark:bg-neutral-900 p-2 text-xs">
                  <div className="muted">{r.by} · {new Date(r.ts).toLocaleString()}</div>
                  <div>{r.text}</div>
                </div>
              ))}
              {t.status !== 'closed' && (
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={reply[t.id] || ''}
                    onChange={(e) => setReply({ ...reply, [t.id]: e.target.value })}
                    placeholder="Reply…"
                    className="flex-1 rounded-md border border-line dark:border-line-dark bg-transparent px-2 py-1 text-xs"
                    data-testid={`admin-ticket-reply-input-${t.id}`}
                  />
                  <button type="button" className="pill pill-accent text-xs" onClick={() => send(t.id)} data-testid={`admin-ticket-reply-send-${t.id}`}>Send</button>
                  <button type="button" className="pill pill-neutral text-xs" onClick={() => close(t.id)} data-testid={`admin-ticket-close-${t.id}`}>Close</button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------
// HEALTH
// ----------------------------------------------------------------------------
function HealthTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const r = await api.get('/api/v1/admin/health');
        setData(r.data);
      } finally { setLoading(false); }
    })();
  }, []);

  if (loading) return <Loader2 className="h-4 w-4 animate-spin muted" />;
  if (!data) return <p className="muted text-sm">Failed to load.</p>;
  const counts = data.counts || {};
  return (
    <section className="space-y-4" data-testid="admin-health-tab">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {Object.entries(counts).map(([k, v]) => (
          <div key={k} className="rounded-md border border-line dark:border-line-dark p-3" data-testid={`admin-count-${k}`}>
            <div className="text-xs uppercase muted">{k}</div>
            <div className="text-2xl font-semibold">{v}</div>
          </div>
        ))}
      </div>
      <div className="rounded-md border border-line dark:border-line-dark p-3">
        <div className="text-xs uppercase muted mb-2">LLM cost aggregate</div>
        {(data.llm_costs || []).length === 0 ? <p className="text-xs muted">No spend yet.</p> : (
          <ul className="text-sm">
            {(data.llm_costs || []).map((c) => (
              <li key={c._id} className="flex justify-between">
                <span>{c._id}</span>
                <span className="muted">${c.cost_usd?.toFixed?.(4) || 0} · {c.n} calls</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------------
// OBSERVABILITY
// ----------------------------------------------------------------------------
function ObservabilityTab({ isAdmin }) {
  const [events, setEvents] = useState([]);
  const [errors, setErrors] = useState([]);
  const [flash, setFlash] = useState(null);

  const load = useCallback(async () => {
    const [e, r] = await Promise.all([
      api.get('/api/v1/admin/observability/events'),
      api.get('/api/v1/admin/observability/errors'),
    ]);
    setEvents(e.data.events || []);
    setErrors(r.data.errors || []);
  }, []);
  useEffect(() => { load(); }, [load]);

  const emit = async () => {
    try {
      await api.post('/api/v1/admin/observability/test-error', { where: 'admin_console' });
      setFlash({ kind: 'ok', message: 'Test error emitted.' });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: 'Emit failed.' });
    }
  };

  return (
    <section className="space-y-4" data-testid="admin-obs-tab">
      {flash && <FlashBanner {...flash} onDismiss={() => setFlash(null)} />}
      <div className="rounded-md border border-line dark:border-line-dark p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs uppercase muted">Internal analytics events</div>
          {isAdmin && <button type="button" className="pill pill-neutral text-xs" onClick={emit} data-testid="admin-obs-emit">Emit test error</button>}
        </div>
        <p className="text-[10px] muted italic mb-2">INTERNAL STUB — PostHog / Sentry equivalent. Not wired to any external service.</p>
        {events.length === 0 ? <p className="text-xs muted">No events yet.</p> : (
          <ul className="text-xs divide-y divide-line dark:divide-line-dark">
            {events.slice(0, 20).map((e) => (
              <li key={e.id} className="py-1 flex justify-between">
                <span className="font-mono">{e.event}</span>
                <span className="muted">{new Date(e.ts).toLocaleString()}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="rounded-md border border-line dark:border-line-dark p-3">
        <div className="text-xs uppercase muted mb-2">Error events</div>
        {errors.length === 0 ? <p className="text-xs muted">No errors.</p> : (
          <ul className="text-xs divide-y divide-line dark:divide-line-dark">
            {errors.slice(0, 20).map((e) => (
              <li key={e.id} className="py-1">
                <div className="font-mono">{e.kind} · {e.where}</div>
                <div className="muted">{new Date(e.ts).toLocaleString()} — {e.message}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

// ----------------------------------------------------------------------------
// Shared flash banner
// ----------------------------------------------------------------------------
function FlashBanner({ kind, message, onDismiss }) {
  return (
    <div className={`rounded-md border px-3 py-2 text-sm flex items-center gap-2 ${kind === 'ok' ? 'bg-accent/10 border-accent/40 text-accent' : 'bg-amber-50 border-amber-400 text-amber-900 dark:bg-amber-950 dark:text-amber-200'}`} data-testid="admin-flash">
      {kind === 'ok' ? <Check className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
      <span className="flex-1">{message}</span>
      {onDismiss && <button type="button" onClick={onDismiss}><X className="h-3 w-3" /></button>}
    </div>
  );
}

// ----------------------------------------------------------------------------
// INTEGRATIONS DASHBOARD (Milestone A · admin-only)
// ----------------------------------------------------------------------------
const STATUS_STYLE = {
  CONNECTED:              'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200',
  TEST_MODE:              'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-200',
  CONFIGURATION_REQUIRED: 'bg-neutral-100 text-neutral-700 dark:bg-neutral-900 dark:text-neutral-300',
  DEGRADED:               'bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300',
  DISABLED:               'bg-neutral-200 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400',
};

function IntegrationsTab({ isAdmin }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busySlug, setBusySlug] = useState(null);
  const [flash, setFlash] = useState(null);
  const [detail, setDetail] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api.get('/api/v1/admin/integrations');
      setRows(r.data.providers || []);
      setSummary(r.data.summary || null);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const test = async (slug) => {
    setBusySlug(slug);
    try {
      const r = await api.post(`/api/v1/admin/integrations/${slug}/test`, {});
      setFlash({ kind: r.data.ok ? 'ok' : 'warn',
                 message: `${slug}: ${r.data.detail || 'no detail'}` });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn',
                 message: e?.response?.data?.detail?.message || `${slug}: test failed.` });
    } finally { setBusySlug(null); }
  };
  const toggle = async (slug, enabled) => {
    setBusySlug(slug);
    try {
      await api.post(`/api/v1/admin/integrations/${slug}/${enabled ? 'disable' : 'enable'}`, {});
      setFlash({ kind: 'ok', message: `${slug}: ${enabled ? 'disabled' : 'enabled'}.` });
      await load();
    } catch (e) {
      setFlash({ kind: 'warn', message: `${slug}: toggle failed.` });
    } finally { setBusySlug(null); }
  };
  const open = async (slug) => {
    setDetail({ loading: true, slug });
    try {
      const r = await api.get(`/api/v1/admin/integrations/${slug}`);
      setDetail({ loading: false, ...r.data });
    } catch (e) {
      setDetail({ loading: false, slug, error: 'Failed to load.' });
    }
  };

  const byCat = rows.reduce((acc, r) => {
    (acc[r.category || 'misc'] = acc[r.category || 'misc'] || []).push(r);
    return acc;
  }, {});

  return (
    <section className="space-y-4" data-testid="admin-integrations-tab">
      {flash && <FlashBanner {...flash} onDismiss={() => setFlash(null)} />}
      {summary && (
        <div className="flex flex-wrap gap-2 text-xs" data-testid="integrations-summary">
          {Object.entries(summary.counts || {}).filter(([, v]) => v > 0).map(([k, v]) => (
            <span key={k} className={`pill text-[10px] ${STATUS_STYLE[k] || 'pill-neutral'}`}>{k}: {v}</span>
          ))}
          <span className="pill pill-neutral text-[10px]">total: {summary.total}</span>
        </div>
      )}
      {loading ? <Loader2 className="h-4 w-4 animate-spin muted" /> : (
        <div className="space-y-6">
          {Object.entries(byCat).sort(([a], [b]) => a.localeCompare(b)).map(([cat, list]) => (
            <div key={cat} className="space-y-2">
              <div className="text-xs uppercase muted tracking-wider">{cat}</div>
              <div className="rounded-md border border-line dark:border-line-dark overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-neutral-50 dark:bg-neutral-900 text-xs uppercase muted">
                    <tr>
                      <th className="text-left px-3 py-2">Provider</th>
                      <th className="text-left px-3 py-2">Status</th>
                      <th className="text-left px-3 py-2">Missing env</th>
                      <th className="text-right px-3 py-2">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {list.map((p) => {
                      const disabled = p.status === 'DISABLED';
                      return (
                        <tr key={p.slug} className="border-t border-line dark:border-line-dark" data-testid={`integration-row-${p.slug}`}>
                          <td className="px-3 py-2">
                            <button type="button" onClick={() => open(p.slug)} className="hover:underline">
                              <span className="font-medium">{p.label}</span>
                              <span className="ml-2 text-[10px] muted font-mono">{p.slug}</span>
                            </button>
                            {p.docs_url && (
                              <a href={p.docs_url} target="_blank" rel="noreferrer" className="ml-2 text-[10px] muted underline">docs</a>
                            )}
                          </td>
                          <td className="px-3 py-2">
                            <span className={`pill text-[10px] ${STATUS_STYLE[p.status] || 'pill-neutral'}`} data-testid={`integration-status-${p.slug}`}>{p.status}</span>
                          </td>
                          <td className="px-3 py-2 text-[11px] font-mono">
                            {(p.missing_env || []).map((k) => <div key={k}>{k}</div>)}
                            {(p.missing_env || []).length === 0 && <span className="muted">—</span>}
                          </td>
                          <td className="px-3 py-2 text-right whitespace-nowrap">
                            <button type="button" onClick={() => test(p.slug)} disabled={!isAdmin || busySlug === p.slug}
                                    className="text-xs underline text-accent disabled:opacity-40 disabled:no-underline mr-3" data-testid={`integration-test-${p.slug}`}>
                              {busySlug === p.slug ? '…' : 'Test'}
                            </button>
                            <button type="button" onClick={() => toggle(p.slug, !disabled)} disabled={!isAdmin || busySlug === p.slug}
                                    className="text-xs underline disabled:opacity-40 disabled:no-underline" data-testid={`integration-toggle-${p.slug}`}>
                              {disabled ? 'Enable' : 'Disable'}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" data-testid="integration-detail-modal">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg border border-line dark:border-line-dark bg-bg dark:bg-bg-dark p-5 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">{detail.label || detail.slug}</h3>
              <button type="button" onClick={() => setDetail(null)}><X className="h-4 w-4" /></button>
            </div>
            {detail.loading ? <Loader2 className="h-4 w-4 animate-spin muted" /> : detail.error ? (
              <p className="text-sm text-red-600">{detail.error}</p>
            ) : (
              <>
                <div className="text-xs muted">
                  Category: <span className="font-medium">{detail.category}</span> ·
                  Status: <span className={`pill text-[10px] ml-1 ${STATUS_STYLE[detail.status] || ''}`}>{detail.status}</span>
                </div>
                <div className="rounded-md border border-line dark:border-line-dark p-3 text-xs space-y-1">
                  <div className="uppercase muted">Env vars</div>
                  <div>Required: <span className="font-mono">{(detail.required_env || []).join(', ') || '—'}</span></div>
                  <div>Optional: <span className="font-mono">{(detail.optional_env || []).join(', ') || '—'}</span></div>
                  <div>Missing:  <span className="font-mono text-red-500">{(detail.missing_env || []).join(', ') || 'none'}</span></div>
                </div>
                {detail.webhook_url && (
                  <div className="rounded-md border border-line dark:border-line-dark p-3 text-xs space-y-1" data-testid="integration-webhook-url">
                    <div className="uppercase muted">Webhook URL (copy into vendor dashboard)</div>
                    <code className="block font-mono break-all">{detail.webhook_url}</code>
                  </div>
                )}
                <div className="rounded-md border border-line dark:border-line-dark p-3 text-xs">
                  <div className="uppercase muted mb-2">Recent events</div>
                  {(detail.recent_events || []).length === 0 ? (
                    <p className="muted">No events yet.</p>
                  ) : (
                    <ul className="divide-y divide-line dark:divide-line-dark">
                      {(detail.recent_events || []).slice(0, 10).map((e, i) => (
                        <li key={i} className="py-1.5">
                          <div className="flex items-center justify-between">
                            <span className="font-mono">{e.kind}</span>
                            <span className="muted">{new Date(e.ts).toLocaleString()}</span>
                          </div>
                          {e.detail?.detail && <div className="muted">{e.detail.detail}</div>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                {detail.last_error && (
                  <div className="rounded-md border border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-950 p-3 text-xs">
                    <div className="text-red-800 dark:text-red-200">Last error</div>
                    <div className="font-mono">{detail.last_error.code}: {detail.last_error.message}</div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

