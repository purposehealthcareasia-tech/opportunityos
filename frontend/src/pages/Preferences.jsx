import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { X, Save, Search, Building2 } from 'lucide-react';
import { api, withIdempotency } from '../lib/api';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import Input from '../components/ui/Input';
import { LoadingBlock, ErrorBlock } from '../lib/scope';

function ChipList({ items, onRemove }) {
  if (!items?.length) return <p className="text-xs muted">Nothing selected yet.</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span key={item} className="pill pill-accent">
          {item}
          <button type="button" onClick={() => onRemove(item)} className="ml-1 opacity-70 hover:opacity-100" aria-label="Remove">
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
    </div>
  );
}

function TaxonomyTypeahead({ selected, onToggle }) {
  const [families, setFamilies] = useState([]);
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await api.get('/api/v1/taxonomy');
        setFamilies(data.families || []);
      } catch (e) { console.debug('taxonomy fetch failed', e); }
      finally { setLoading(false); }
    })();
  }, []);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return families.slice(0, 8);
    return families.filter((f) => f.family.toLowerCase().includes(needle) || (f.synonyms || []).some((s) => s.toLowerCase().includes(needle))).slice(0, 12);
  }, [families, q]);

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 muted pointer-events-none" />
        <input className="field-input pl-9" placeholder="Search role families or synonyms…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {loading ? <LoadingBlock label="Loading taxonomy…" /> : (
        <div className="grid md:grid-cols-2 gap-1">
          {filtered.map((f) => {
            const on = selected.includes(f.family);
            return (
              <button key={f.family} type="button" onClick={() => onToggle(f.family)} className={`text-left rounded-md border px-3 py-2 text-sm transition-colors ${on ? 'border-accent bg-accent/5 text-ink dark:text-ink-dark' : 'border-line dark:border-line-dark muted hover:text-ink dark:hover:text-ink-dark'}`}>
                <div className="font-medium">{f.family}</div>
                {f.synonyms?.length ? <div className="text-[11px] muted mt-0.5 truncate">{f.synonyms.slice(0, 4).join(' · ')}</div> : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function CompanyTypeahead({ label, selected, onToggle, placeholder }) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const t = setTimeout(async () => {
      if (!q.trim()) { setResults([]); return; }
      setLoading(true);
      try {
        const { data } = await api.get(`/api/v1/companies?q=${encodeURIComponent(q)}`);
        if (!cancelled) setResults(data.companies || []);
      } catch (e) { console.debug('company typeahead search failed', e); }
      finally { if (!cancelled) setLoading(false); }
    }, 200);
    return () => { cancelled = true; clearTimeout(t); };
  }, [q]);

  const handleKey = (e) => {
    if (e.key === 'Enter' && q.trim()) {
      e.preventDefault();
      onToggle(q.trim().toLowerCase());
      setQ('');
    }
  };

  return (
    <div className="space-y-2">
      <label className="field-label">{label}</label>
      <div className="relative">
        <Building2 className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 muted pointer-events-none" />
        <input className="field-input pl-9" placeholder={placeholder} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={handleKey} />
      </div>
      {loading ? <p className="text-xs muted">Searching…</p> : results.length > 0 && (
        <div className="rounded-card border border-line dark:border-line-dark divide-y divide-line dark:divide-line-dark max-h-56 overflow-auto">
          {results.map((r) => (
            <button key={r.domain} type="button" className="w-full text-left px-3 py-2 text-sm hover:bg-neutral-50 dark:hover:bg-neutral-800 flex items-center justify-between gap-3" onClick={() => { onToggle(r.domain); setQ(''); }}>
              <span><span className="font-medium">{r.name}</span> <span className="muted text-xs">{r.domain}</span></span>
              <span className="text-xs muted">Add</span>
            </button>
          ))}
        </div>
      )}
      <ChipList items={selected} onRemove={(v) => onToggle(v)} />
    </div>
  );
}

const DEFAULT_PREFS = {
  role_families: [],
  locations: [],
  remote_ok: false,
  salary_floor_usd: null,
  search_intensity: 'medium',
  employer_include: [],
  employer_exclude: [],
  notes: '',
};

export default function PreferencesPage() {
  const [prefs, setPrefs] = useState(DEFAULT_PREFS);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);
  const [error, setError] = useState('');
  const [locInput, setLocInput] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const { data } = await api.get('/api/v1/preferences/me');
      setVersion(data.version);
      if (data.payload) setPrefs({ ...DEFAULT_PREFS, ...data.payload });
      setSavedAt(data.updated_at);
    } catch (e) {
      const detail = e?.response?.data?.detail;
      if (detail?.error === 'consent_required') setError('You need process_career_data consent to load preferences. Grant it in Settings.');
      else setError('Could not load your preferences.');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const patch = (upd) => setPrefs((p) => ({ ...p, ...upd }));
  const toggleFamily = (name) => setPrefs((p) => ({ ...p, role_families: p.role_families.includes(name) ? p.role_families.filter((x) => x !== name) : [...p.role_families, name] }));
  const addLocation = () => {
    const v = locInput.trim();
    if (!v) return;
    if (!prefs.locations.includes(v)) patch({ locations: [...prefs.locations, v] });
    setLocInput('');
  };
  const removeLocation = (v) => patch({ locations: prefs.locations.filter((x) => x !== v) });
  const toggleInclude = (d) => patch({ employer_include: prefs.employer_include.includes(d) ? prefs.employer_include.filter((x) => x !== d) : [...prefs.employer_include, d] });
  const toggleExclude = (d) => patch({ employer_exclude: prefs.employer_exclude.includes(d) ? prefs.employer_exclude.filter((x) => x !== d) : [...prefs.employer_exclude, d] });

  const save = async () => {
    setSaving(true); setError('');
    try {
      const { data } = await api.post('/api/v1/preferences', prefs, withIdempotency());
      setVersion(data.version);
      setSavedAt(data.updated_at);
    } catch (e) {
      setError(e?.response?.data?.detail?.error === 'consent_required'
        ? 'You need process_career_data consent to save preferences. Grant it in Settings.'
        : 'Could not save preferences.');
    } finally { setSaving(false); }
  };

  if (loading) return <div className="max-w-3xl mx-auto"><LoadingBlock label="Loading preferences…" /></div>;

  return (
    <div className="max-w-3xl mx-auto space-y-6 animate-fadeIn">
      <div className="flex items-baseline justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Preferences</h1>
          <p className="muted text-sm mt-1">What kind of roles, where, at what floor. Saves append a new version — the latest wins.</p>
        </div>
        <div className="text-xs muted">Version {version}{savedAt ? ` · saved ${new Date(savedAt).toLocaleString()}` : ''}</div>
      </div>

      {error && <ErrorBlock message={error} onRetry={load} />}

      <Card>
        <CardHeader title="Role families" subtitle="Choose the families you want to see in your feed. Typeahead searches both family names and synonyms." />
        <TaxonomyTypeahead selected={prefs.role_families} onToggle={toggleFamily} />
        <div className="mt-3"><ChipList items={prefs.role_families} onRemove={toggleFamily} /></div>
      </Card>

      <Card>
        <CardHeader title="Locations" subtitle="Free-form city or region. Press Enter to add a chip." />
        <div className="flex items-center gap-2">
          <input className="field-input" placeholder="e.g. Phoenix, AZ" value={locInput} onChange={(e) => setLocInput(e.target.value)} onKeyDown={(e) => (e.key === 'Enter' ? (e.preventDefault(), addLocation()) : null)} />
          <Button variant="secondary" onClick={addLocation}>Add</Button>
        </div>
        <div className="mt-3"><ChipList items={prefs.locations} onRemove={removeLocation} /></div>
        <label className="flex items-center gap-2 mt-4 text-sm">
          <input type="checkbox" checked={prefs.remote_ok} onChange={(e) => patch({ remote_ok: e.target.checked })} className="h-4 w-4 rounded border-line dark:border-line-dark accent-emerald-700" />
          I’m open to fully remote roles.
        </label>
      </Card>

      <Card>
        <CardHeader title="Comp floor" subtitle="Private — never shared with employers. Used only to filter your feed." />
        <div className="flex items-center gap-3 max-w-sm">
          <span className="muted text-sm">USD</span>
          <Input
            type="number"
            min={0}
            step={5000}
            placeholder="e.g. 135000"
            value={prefs.salary_floor_usd ?? ''}
            onChange={(e) => patch({ salary_floor_usd: e.target.value === '' ? null : Number(e.target.value) })}
          />
        </div>
        <p className="text-xs muted mt-2">We never expose this number to employers. It only trims your feed.</p>
      </Card>

      <Card>
        <CardHeader title="Search intensity" subtitle="How many opportunities you want to see per week." />
        <div className="grid md:grid-cols-3 gap-2">
          {[
            { k: 'low', label: 'Low', hint: 'A handful per week; only high-fit roles.' },
            { k: 'medium', label: 'Medium', hint: 'A steady stream; balanced fit vs volume.' },
            { k: 'high', label: 'High', hint: 'Everything we surface as plausibly-fit.' },
          ].map((opt) => (
            <button key={opt.k} type="button" onClick={() => patch({ search_intensity: opt.k })} className={`rounded-md border px-3 py-3 text-left transition-colors ${prefs.search_intensity === opt.k ? 'border-accent bg-accent/5' : 'border-line dark:border-line-dark'}`}>
              <div className="text-sm font-medium">{opt.label}</div>
              <div className="text-xs muted mt-0.5">{opt.hint}</div>
            </button>
          ))}
        </div>
      </Card>

      <Card>
        <CardHeader title="Employer allow/block lists" subtitle="Include lists give a bump; exclude lists suppress. Free-form domains accepted (press Enter)." />
        <div className="grid md:grid-cols-2 gap-6">
          <CompanyTypeahead label="Include" selected={prefs.employer_include} onToggle={toggleInclude} placeholder="Search or paste a domain…" />
          <CompanyTypeahead label="Exclude" selected={prefs.employer_exclude} onToggle={toggleExclude} placeholder="Search or paste a domain…" />
        </div>
      </Card>

      <div className="flex items-center justify-end gap-3">
        <Button variant="accent" onClick={save} loading={saving}><Save className="h-4 w-4" /> Save preferences</Button>
      </div>
    </div>
  );
}
