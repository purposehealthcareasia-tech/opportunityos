// Mirror of backend /api/v1/meta/policy for the signup screen. If the backend is reachable at page
// load, we fetch the live catalog and merge; this fallback keeps the UI honest when offline.
export const POLICY_TEXT_VERSION_FALLBACK = '1.0';

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
];
