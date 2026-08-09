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
    {
        # Phase 5a (2026-08-09) — resume-free public Passport share link.
        # Revocable, TTL-bounded, every view receipted.
        "scope": "share_passport",
        "required": False,
        "label": "Generate resume-free share links for my Passport",
        "description": "Let Fynd create signed, revocable public links so an employer can see the Passport claims I approved — without me sending them a résumé. Every view is receipted. I can revoke any link at any time and revocation is honored immediately.",
    },
    {
        # Phase 5d (2026-08-09) — interview prep generation grounded in
        # approved Passport claims only. LLM output constrained by the
        # validation firewall: no claim, no sentence.
        "scope": "interview_prep_generate",
        "required": False,
        "label": "Generate interview practice grounded in my Passport",
        "description": "Let Fynd use my APPROVED Passport claims to generate practice prompts and mock Q&A. Output is clearly labeled 'practice'. No claim, no sentence — the generator refuses to invent anything I haven't approved.",
    },
    {
        # Phase 5i (2026-08-09) — Passport-as-API third-party access via
        # per-scope tokens (hash-stored). Every access receipted.
        "scope": "passport_api_access",
        "required": False,
        "label": "Grant third-party Passport-as-API access via per-scope tokens",
        "description": "Let Fynd mint per-scope API tokens I can give to third-party verifiers. Each token grants access to a specific claim subset for a limited time; every access is receipted; I can revoke any token immediately.",
    },
]

SCOPE_KEYS = {s["scope"] for s in CONSENT_SCOPES}
REQUIRED_SCOPES = {s["scope"] for s in CONSENT_SCOPES if s["required"]}


def policy_version() -> str:
    return settings.POLICY_TEXT_VERSION
