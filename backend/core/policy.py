"""Consent policy text — versioned. Frontend and backend must agree on the version string.

When you materially change the copy of any consent scope, bump POLICY_TEXT_VERSION and
coordinate with the frontend copy.
"""
from core.config import settings

CONSENT_SCOPES = [
    {
        "scope": "process_career_data",
        "required": True,
        "label": "Process my career information",
        "description": "Let Fynd process the résumé data, claims, and projects I approve so I can build a verified Career Passport.",
    },
    {
        "scope": "discover_jobs",
        "required": False,
        "label": "Surface job opportunities",
        "description": "Let Fynd discover job openings that match my approved Career Passport.",
    },
    {
        "scope": "generate_materials",
        "required": False,
        "label": "Draft grounded application materials",
        "description": "Let Fynd help me draft résumés and cover letters grounded strictly in my approved Passport. Every draft is reviewed by me before it leaves my account.",
    },
    {
        "scope": "track_applications",
        "required": False,
        "label": "Track applications I send",
        "description": "Record the status of applications I explicitly submit so I can see the pipeline.",
    },
    {
        "scope": "email_me",
        "required": False,
        "label": "Email me updates",
        "description": "Send me periodic email updates about relevant opportunities and changes to my Passport.",
    },
    {
        # Phase 4 (Founder Brief · Item 3/5) — first-class batch-authorization
        # scope for real submit / email-route dispatch. Grantable + revocable.
        # Required for: /api/v1/sprint/*, /api/v1/email-route/*.
        "scope": "submit_applications",
        "required": False,
        "label": "Submit applications on my behalf (dry-run in preview)",
        "description": "Authorize Fynd to submit applications you explicitly approve. In preview this is DRY-RUN only — nothing is sent to a real employer without a separate per-application confirmation. Revocable at any time.",
    },
]

SCOPE_KEYS = {s["scope"] for s in CONSENT_SCOPES}
REQUIRED_SCOPES = {s["scope"] for s in CONSENT_SCOPES if s["required"]}


def policy_version() -> str:
    return settings.POLICY_TEXT_VERSION
