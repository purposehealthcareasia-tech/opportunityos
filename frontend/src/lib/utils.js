export function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return String(iso); }
}

export function prettyValue(value) {
  if (value == null) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.join(', ');
  // object
  const entries = Object.entries(value).filter(([, v]) => v !== null && v !== undefined && v !== '');
  if (!entries.length) return '—';
  return entries.map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : typeof v === 'object' ? JSON.stringify(v) : v}`).join('  ·  ');
}

export function sourceChip(src) {
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

export function sortGroups(groups) {
  return [...groups].sort((a, b) => {
    const ai = CLAIM_TYPE_ORDER.indexOf(a.type);
    const bi = CLAIM_TYPE_ORDER.indexOf(b.type);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });
}
