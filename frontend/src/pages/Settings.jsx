import React, { useEffect, useMemo, useState, useCallback } from 'react';
import Card, { CardHeader } from '../components/ui/Card';
import Input from '../components/ui/Input';
import Button from '../components/ui/Button';
import ThemeToggle from '../components/ThemeToggle';
import NotificationsSettings from '../components/NotificationsSettings';
import { useAuth } from '../lib/auth';
import { api, withIdempotency } from '../lib/api';
import { rebrandScopeCatalog } from '../lib/consentScopes';
import { Loader2, ShieldCheck, ShieldOff } from 'lucide-react';

function useConsentState() {
  const [state, setState] = useState({ scopes: [], policy_text_version: '1.0' });
  const [catalog, setCatalog] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [meta, live] = await Promise.all([
        api.get('/api/v1/meta/policy'),
        api.get('/api/v1/consents'),
      ]);
      setCatalog(rebrandScopeCatalog(meta.data.scopes || []));
      setState(live.data);
    } catch (e) {
      setError('Could not load consent scopes.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return { state, catalog, loading, error, reload: load };
}

function ConsentRow({ scope, meta, granted, ts, onChange, saving }) {
  return (
    <div className="flex items-start justify-between gap-4 py-4 border-b border-line dark:border-line-dark last:border-b-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">{meta?.label || scope}</span>
          {meta?.required && <span className="pill pill-neutral">required</span>}
          <span className={granted ? 'pill pill-accent' : 'pill pill-neutral'}>
            {granted ? <><ShieldCheck className="h-3 w-3"/>granted</> : <><ShieldOff className="h-3 w-3"/>revoked</>}
          </span>
        </div>
        <p className="text-xs muted mt-1 leading-relaxed">{meta?.description}</p>
        {ts && <p className="text-[11px] muted mt-1">Last change: {new Date(ts).toLocaleString()}</p>}
      </div>
      <div className="flex-shrink-0">
        {granted ? (
          <Button variant="secondary" size="sm" onClick={() => onChange(false)} loading={saving}>Revoke</Button>
        ) : (
          <Button variant="accent" size="sm" onClick={() => onChange(true)} loading={saving}>Grant</Button>
        )}
      </div>
    </div>
  );
}

export default function Settings() {
  const { user, refresh } = useAuth();
  const [profile, setProfile] = useState({ name: user?.name || '' });
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMsg, setProfileMsg] = useState('');

  const [pwdForm, setPwdForm] = useState({ current_password: '', new_password: '', confirm: '' });
  const [savingPwd, setSavingPwd] = useState(false);
  const [pwdMsg, setPwdMsg] = useState('');
  const [pwdError, setPwdError] = useState('');

  const { state: consentState, catalog, loading: cLoading, error: cError, reload } = useConsentState();
  const [savingScope, setSavingScope] = useState(null);

  useEffect(() => { setProfile({ name: user?.name || '' }); }, [user]);

  const catalogByScope = useMemo(() => Object.fromEntries(catalog.map((c) => [c.scope, c])), [catalog]);

  async function saveProfile(e) {
    e.preventDefault();
    setSavingProfile(true); setProfileMsg('');
    try {
      await api.patch('/api/v1/users/me', { name: profile.name.trim() }, withIdempotency());
      await refresh();
      setProfileMsg('Saved.');
    } catch {
      setProfileMsg('Could not save profile.');
    } finally { setSavingProfile(false); }
  }

  async function changePwd(e) {
    e.preventDefault();
    setPwdMsg(''); setPwdError('');
    if (pwdForm.new_password.length < 8) { setPwdError('New password must be at least 8 characters.'); return; }
    if (pwdForm.new_password !== pwdForm.confirm) { setPwdError('New passwords do not match.'); return; }
    setSavingPwd(true);
    try {
      await api.post('/api/v1/users/me/change-password', {
        current_password: pwdForm.current_password,
        new_password: pwdForm.new_password,
      }, withIdempotency());
      setPwdForm({ current_password: '', new_password: '', confirm: '' });
      setPwdMsg('Password updated.');
    } catch (err) {
      const detail = err?.response?.data?.detail;
      setPwdError(detail === 'current_password_incorrect' ? 'Your current password is incorrect.' : 'Could not update password.');
    } finally { setSavingPwd(false); }
  }

  async function toggleScope(scope, next) {
    setSavingScope(scope);
    try {
      await api.post('/api/v1/consents', {
        scope,
        granted: next,
        policy_text_version: consentState.policy_text_version,
      }, withIdempotency());
      await reload();
    } catch (err) {
      // If backend forbids (e.g., required scope guard in another phase), surface it
      // but we do not treat consent errors as fatal.
      alert(err?.response?.data?.detail?.error || 'Could not update consent.');
    } finally {
      setSavingScope(null);
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-8 animate-fadeIn">
      <div>
        <h1 className="text-2xl font-semibold">Settings</h1>
        <p className="muted mt-1 text-sm">Profile, security, and the consent ledger for your account.</p>
      </div>

      <Card>
        <CardHeader title="Profile" subtitle="Your name is used across the product interface." />
        <form onSubmit={saveProfile} className="space-y-4">
          <Input label="Email" value={user?.email || ''} disabled hint="Email cannot be changed in this phase." />
          <Input label="Full name" value={profile.name} onChange={(e) => setProfile({ name: e.target.value })} required />
          <div className="flex items-center justify-between">
            <span className="text-xs muted">{profileMsg}</span>
            <Button type="submit" loading={savingProfile}>Save changes</Button>
          </div>
        </form>
      </Card>

      <Card>
        <CardHeader title="Theme" subtitle="Choose how Fynd looks on this device." />
        <div className="flex items-center justify-between">
          <span className="text-sm muted">Light and dark modes are both first-class.</span>
          <ThemeToggle />
        </div>
      </Card>

      <NotificationsSettings />

      <Card>
        <CardHeader title="Change password" subtitle="Choose a password you don't use anywhere else." />
        <form onSubmit={changePwd} className="space-y-4">
          <Input label="Current password" type="password" value={pwdForm.current_password} onChange={(e) => setPwdForm({ ...pwdForm, current_password: e.target.value })} required autoComplete="current-password" />
          <div className="grid md:grid-cols-2 gap-4">
            <Input label="New password" type="password" value={pwdForm.new_password} onChange={(e) => setPwdForm({ ...pwdForm, new_password: e.target.value })} required autoComplete="new-password" hint="At least 8 characters." />
            <Input label="Confirm new password" type="password" value={pwdForm.confirm} onChange={(e) => setPwdForm({ ...pwdForm, confirm: e.target.value })} required autoComplete="new-password" />
          </div>
          {pwdError && <div className="rounded-md border border-red-500/30 bg-red-500/5 text-red-700 dark:text-red-300 text-sm px-3 py-2">{pwdError}</div>}
          <div className="flex items-center justify-between">
            <span className="text-xs text-accent">{pwdMsg}</span>
            <Button type="submit" loading={savingPwd}>Update password</Button>
          </div>
        </form>
      </Card>

      <Card>
        <CardHeader
          title="Consent scopes"
          subtitle={`Append-only ledger · policy v${consentState.policy_text_version}`}
          action={<span className="text-xs muted">Revocation logs a new row; nothing is ever deleted.</span>}
        />
        {cLoading ? (
          <div className="flex items-center gap-2 muted text-sm py-6"><Loader2 className="h-4 w-4 animate-spin"/> Loading consent state…</div>
        ) : cError ? (
          <p className="text-sm text-red-600 dark:text-red-400">{cError}</p>
        ) : (
          <div>
            {consentState.scopes.map((s) => (
              <ConsentRow
                key={s.scope}
                scope={s.scope}
                meta={catalogByScope[s.scope]}
                granted={s.granted}
                ts={s.ts}
                saving={savingScope === s.scope}
                onChange={(next) => toggleScope(s.scope, next)}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
