import React, { useState } from 'react';
import { Building2, Send, CheckCircle2, AlertCircle } from 'lucide-react';
import { api } from '../lib/api';

export default function EmployerIntake() {
  const [form, setForm] = useState({
    company_name: '',
    contact_name: '',
    contact_email: '',
    contact_role: '',
    ats_name: '',
    open_roles_count: '',
    notes: '',
    website_url_confirm: '', // honeypot; humans leave blank
  });
  const [state, setState] = useState({ status: 'idle', error: null, id: null });

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    setState({ status: 'submitting', error: null, id: null });
    try {
      const payload = { ...form };
      if (payload.open_roles_count === '') delete payload.open_roles_count;
      else payload.open_roles_count = Number(payload.open_roles_count) || 0;
      const { data } = await api.post('/api/v1/employer-intake', payload);
      setState({ status: 'ok', error: null, id: data.id });
    } catch (err) {
      const d = err?.response?.data?.detail;
      const msg = d?.message || d?.error || 'Something went wrong. Please try again.';
      setState({ status: 'err', error: msg, id: null });
    }
  };

  if (state.status === 'ok') {
    return (
      <div className="max-w-xl mx-auto py-16 px-6" data-testid="employer-intake-success">
        <div className="card p-8 text-center space-y-3">
          <CheckCircle2 className="h-8 w-8 text-accent mx-auto" />
          <h1 className="text-xl font-semibold text-ink dark:text-ink-dark">Thanks — we'll be in touch</h1>
          <p className="text-sm muted leading-relaxed">
            Your OpportunityOS intake has been recorded. A member of the team will reply to <span className="font-mono">{form.contact_email}</span> to discuss connecting your ATS.
          </p>
          <p className="text-xs muted">Reference: <span className="font-mono">{state.id}</span></p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto py-12 px-6" data-testid="employer-intake-page">
      <div className="mb-8">
        <div className="inline-flex items-center gap-2 mb-3">
          <Building2 className="h-5 w-5 text-accent" />
          <span className="text-xs font-mono tracking-wide muted uppercase">For employers</span>
        </div>
        <h1 className="text-2xl md:text-3xl font-semibold text-ink dark:text-ink-dark">
          Connect your ATS to OpportunityOS
        </h1>
        <p className="text-sm muted mt-2 leading-relaxed">
          We surface real, consent-based candidates from our Passport-verified pool. Tell us about your open roles and we'll walk you through the fastest way to plug in — usually Greenhouse, Lever, or Ashby's public boards.
        </p>
      </div>

      <form onSubmit={submit} className="card p-6 space-y-4" data-testid="employer-intake-form">
        <Field label="Company name *" testid="employer-company-input">
          <input required maxLength={200} type="text" value={form.company_name}
                 onChange={set('company_name')} className="input"
                 data-testid="employer-company-input" />
        </Field>
        <div className="grid md:grid-cols-2 gap-4">
          <Field label="Your name *" testid="employer-contact-name-input">
            <input required maxLength={150} type="text" value={form.contact_name}
                   onChange={set('contact_name')} className="input"
                   data-testid="employer-contact-name-input" />
          </Field>
          <Field label="Your role" testid="employer-contact-role-input">
            <input maxLength={150} type="text" value={form.contact_role}
                   onChange={set('contact_role')} className="input"
                   placeholder="Talent Lead / Recruiter / Founder"
                   data-testid="employer-contact-role-input" />
          </Field>
        </div>
        <Field label="Work email *" testid="employer-contact-email-input">
          <input required maxLength={200} type="email" value={form.contact_email}
                 onChange={set('contact_email')} className="input"
                 data-testid="employer-contact-email-input" />
        </Field>
        <div className="grid md:grid-cols-2 gap-4">
          <Field label="Your ATS (if any)" testid="employer-ats-input">
            <input maxLength={100} type="text" value={form.ats_name}
                   onChange={set('ats_name')} className="input"
                   placeholder="Greenhouse, Lever, Ashby, Workday…"
                   data-testid="employer-ats-input" />
          </Field>
          <Field label="Open roles right now" testid="employer-open-roles-input">
            <input min="0" max="10000" type="number" value={form.open_roles_count}
                   onChange={set('open_roles_count')} className="input"
                   data-testid="employer-open-roles-input" />
          </Field>
        </div>
        <Field label="Anything else we should know?" testid="employer-notes-input">
          <textarea maxLength={2000} rows={4} value={form.notes} onChange={set('notes')}
                     className="input" placeholder="Locations, must-have credentials, hiring timelines…"
                     data-testid="employer-notes-input" />
        </Field>
        {/* Honeypot — hidden from real users; bots often fill every field */}
        <div style={{ position: 'absolute', left: '-9999px', opacity: 0, height: 0 }}
             aria-hidden="true">
          <label>
            Website confirm (leave blank):
            <input type="text" tabIndex={-1} autoComplete="off"
                    value={form.website_url_confirm}
                    onChange={set('website_url_confirm')} />
          </label>
        </div>
        {state.error && (
          <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-700 dark:text-red-300">
            <AlertCircle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>{state.error}</span>
          </div>
        )}
        <div className="flex items-center justify-between pt-2">
          <p className="text-xs muted">We never share your email publicly. No auto-marketing.</p>
          <button
            type="submit"
            disabled={state.status === 'submitting'}
            className="inline-flex items-center gap-2 rounded-md bg-accent text-white px-4 py-2 text-sm font-medium hover:opacity-90 disabled:opacity-60"
            data-testid="employer-intake-submit"
          >
            <Send className="h-4 w-4" />
            {state.status === 'submitting' ? 'Sending…' : 'Send'}
          </button>
        </div>
      </form>

      <p className="text-xs muted mt-6 text-center">
        Prefer email? Reach us at <a className="text-accent hover:underline" href="mailto:employers@opportunityos.dev">employers@opportunityos.dev</a>.
      </p>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block text-sm text-ink dark:text-ink-dark">
      <span className="block text-xs font-medium mb-1">{label}</span>
      {children}
    </label>
  );
}
