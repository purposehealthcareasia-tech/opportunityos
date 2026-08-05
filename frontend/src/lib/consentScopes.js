// Mirror of backend /api/v1/meta/policy for the signup screen. If the backend is reachable at page
// load, we fetch the live catalog and merge; this fallback keeps the UI honest when offline.
export const POLICY_TEXT_VERSION_FALLBACK = '1.0';

/**
 * Merge helper — backend `/api/v1/meta/policy` still ships four legacy scope
 * descriptions that reference the pre-rebrand name ("Let OpportunityOS…" /
 * "Authorize OpportunityOS…"). Fixing the backend copy is a Python edit
 * that would trigger uvicorn's --reload watchdog and interrupt the running
 * AAB observation window. Until the founder authorizes a backend touch,
 * this helper substitutes the correctly-branded copy from
 * CONSENT_SCOPES_FALLBACK on top of every backend scope by matching `scope`
 * key. Order is: backend row (label / required / scope) wins where present;
 * description falls back to the local fallback string when the backend
 * description contains the legacy brand. Frontend-only, zero backend risk.
 */
export function rebrandScopeCatalog(backendScopes) {
  if (!Array.isArray(backendScopes)) return CONSENT_SCOPES_FALLBACK;
  const byKey = Object.fromEntries(CONSENT_SCOPES_FALLBACK.map((s) => [s.scope, s]));
  return backendScopes.map((row) => {
    const local = byKey[row.scope];
    if (!local) return row;
    const backendDesc = row.description || '';
    const legacyBrand = /opportunityos/i.test(backendDesc);
    return {
      ...row,
      description: legacyBrand ? local.description : backendDesc,
      label: row.label || local.label,
    };
  });
}

export const CONSENT_SCOPES_FALLBACK = [
  {
    scope: 'process_career_data',
    required: true,
    label: 'Process my career information',
    description:
      'Let Fynd process the résumé data, claims, and projects I approve so I can build a verified Career Passport.',
  },
  {
    scope: 'discover_jobs',
    required: false,
    label: 'Surface job opportunities',
    description: 'Let Fynd discover job openings that match my approved Career Passport.',
  },
  {
    scope: 'generate_materials',
    required: false,
    label: 'Draft grounded application materials',
    description:
      'Let Fynd help me draft résumés and cover letters grounded strictly in my approved Passport. Every draft is reviewed by me before it leaves my account.',
  },
  {
    scope: 'track_applications',
    required: false,
    label: 'Track applications I send',
    description: 'Record the status of applications I explicitly submit so I can see the pipeline.',
  },
  {
    scope: 'email_me',
    required: false,
    label: 'Email me updates',
    description: 'Send me periodic email updates about relevant opportunities and changes to my Passport.',
  },
  {
    // Phase 4 dispatch-authorization scope. Fallback description mirrors the
    // rebranded backend copy (source in `backend/core/policy.py` still says
    // "OpportunityOS" — kept out of scope for Phase 0 to avoid a backend
    // reload during the AAB observation window; see PHASE-0-EVIDENCE §15).
    scope: 'submit_applications',
    required: false,
    label: 'Submit applications on my behalf (dry-run in preview)',
    description: 'Authorize Fynd to submit applications you explicitly approve. In preview this is DRY-RUN only — nothing is sent to a real employer without a separate per-application confirmation. Revocable at any time.',
  },
];
