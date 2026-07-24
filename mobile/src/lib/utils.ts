export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleDateString(); } catch { return String(iso); }
}

export function prettyValue(value: any): string {
  if (value == null) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.join(', ');
  const entries = Object.entries(value).filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (!entries.length) return '—';
  return entries.map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : v}`).join('  ·  ');
}

export function sourceChip(src: any) {
  const kind = src?.kind || 'user_provided';
  if (kind === 'resume_parse') return { label: `LLM parse · ${src?.model || 'model'}`, tone: 'accent' };
  if (kind === 'user_edited') return { label: 'User edited', tone: 'neutral' };
  return { label: 'You entered', tone: 'neutral' };
}

export const CLAIM_TYPE_ORDER = [
  'identity', 'contact', 'location', 'link',
  'education', 'employment', 'project',
  'skill', 'certification', 'publication',
  'comp_expectation', 'availability', 'preference',
  'work_auth', 'visa_timeline',
];

export function sortGroups(groups: any[]) {
  return [...groups].sort((a: any, b: any) => {
    const ai = CLAIM_TYPE_ORDER.indexOf(a.type);
    const bi = CLAIM_TYPE_ORDER.indexOf(b.type);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
}

export const REASON_LABELS: Record<string, string> = {
  requires_us_person: 'US-person required (ITAR)',
  no_sponsorship_offered: 'No sponsorship offered',
  work_auth_mismatch: 'Work-auth mismatch',
  below_salary_floor: 'Below your salary floor',
  location_mismatch: 'Location mismatch',
  employer_excluded: 'On your exclude list',
  duplicate_application: 'You already applied',
  job_not_live: 'Not currently live',
};

export const STATE_LABELS: Record<string, string> = {
  shortlisted: 'Shortlisted',
  preparing: 'Preparing',
  awaiting_approval: 'Awaiting approval',
  approved: 'Approved',
  submitting: 'Submitting',
  submitted: 'Submitted',
  response: 'Response',
  interview: 'Interview',
  offer: 'Offer',
  closed: 'Closed',
};
