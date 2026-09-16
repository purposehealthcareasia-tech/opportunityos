"""FYND ATLAS Application Route Engine — seven route types.

Every opportunity in the platform resolves to EXACTLY ONE route type.
The route type encodes how the platform actually delivers a candidate
into the employer's pipeline, plus every guardrail the ATLAS requires
around it.

The seven route types (rail-ordered from most-automated to no-apply):

  1. DIRECT_ATS_API             — public/documented ATS (Greenhouse,
                                  Lever, Ashby) — high automation
                                  possible after per-app authorization.
  2. STRUCTURED_ATS_FORM        — enterprise ATS with a stable
                                  structured form (Workday, Taleo,
                                  iCIMS). Automation gated on the
                                  form-map coverage + accuracy lock.
  3. UNSTRUCTURED_WEB_FORM      — bespoke employer career site. No
                                  structured contract; automation
                                  UNPERMITTED. Candidate submits
                                  through a template preview.
  4. EMAIL_SUBMISSION           — jobs@ / careers@ mailbox. Automation
                                  UNPERMITTED (own-mailbox path with
                                  per-send human approval only).
  5. FEDERAL_PORTAL             — USAJOBS. Federal-specific rules;
                                  automation UNPERMITTED (deep-link
                                  + evidence-only submission).
  6. PARTNER_REFERRAL           — internal referral or warm-intro
                                  network. Route delivers a shareable
                                  intro packet; submission is by the
                                  human of record.
  7. NO_APPLY_PATH              — the posting has no first-party
                                  submission surface (deep-link to
                                  the company site only). SUBMISSION
                                  RESTRICTED — preparation may run,
                                  send may not.

Every route carries:
  * `automation_level`             — one of {automated, assisted,
                                     manual, unpermitted}
  * `required_candidate_actions`   — the specific human-in-the-loop
                                     steps
  * `limitations`                  — what will NOT happen automatically
  * `approval_requirement`         — the authorization gate that MUST
                                     be present per submit
  * `authorization_expiry_hint`    — how long a granted authorization
                                     stays valid before re-consent
  * `expected_receipt`             — the truthful receipt shape the
                                     platform will produce
  * `submission_permitted`         — hard boolean; the runtime MUST
                                     refuse to send on False, even if
                                     every other rail is green.

The `resolve_route` classifier is deterministic: for a given
opportunity dict shape (`source_ats`, `apply_url`, `email_apply`,
`hiring_path`, etc.) there is exactly one route answer. Ambiguity is
resolved conservatively toward LESS automation, never more.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final
from urllib.parse import urlparse


class RouteType(str, Enum):
    """The seven ATLAS route types. String-Enum for JSON-friendly
    serialization + safe equality with plain strings."""
    DIRECT_ATS_API        = "direct_ats_api"
    STRUCTURED_ATS_FORM   = "structured_ats_form"
    UNSTRUCTURED_WEB_FORM = "unstructured_web_form"
    EMAIL_SUBMISSION      = "email_submission"
    FEDERAL_PORTAL        = "federal_portal"
    PARTNER_REFERRAL      = "partner_referral"
    NO_APPLY_PATH         = "no_apply_path"


class AutomationLevel(str, Enum):
    """How autonomously the platform can act on the route.

    * `automated`   — platform can submit after per-app authorization
                      without step-by-step human clicks.
    * `assisted`    — platform builds the packet, human clicks send.
    * `manual`      — platform prepares the packet, human executes
                      the send end-to-end.
    * `unpermitted` — automation is forbidden (constitutional or
                      accuracy-lock).
    """
    AUTOMATED   = "automated"
    ASSISTED    = "assisted"
    MANUAL      = "manual"
    UNPERMITTED = "unpermitted"


@dataclass(frozen=True)
class RouteSpec:
    """Immutable declaration of one route type's contract."""
    type: RouteType
    automation_level: AutomationLevel
    submission_permitted: bool
    required_candidate_actions: tuple[str, ...]
    limitations: tuple[str, ...]
    approval_requirement: str
    authorization_expiry_hint: str
    expected_receipt: str
    resolution_evidence: tuple[str, ...] = field(default_factory=tuple)


# ==================================================================
# Route specifications — one per RouteType. Totality tested.
# ==================================================================
_R_DIRECT_ATS_API = RouteSpec(
    type=RouteType.DIRECT_ATS_API,
    automation_level=AutomationLevel.AUTOMATED,
    submission_permitted=True,
    required_candidate_actions=(
        "Grant per-application submission authorization.",
        "Confirm the target profile snapshot (resume + answers).",
    ),
    limitations=(
        "No screener-question hallucination — unresolved screeners "
        "surface to the candidate before send.",
        "Automation halts on any ATS-returned validation error.",
    ),
    approval_requirement="per_application_authorization_scope",
    authorization_expiry_hint="72h after grant, or re-consent per app",
    expected_receipt=(
        "signed_submission_receipt: {external_ref, submitted_at, "
        "ats_response_id, evidence_hash}"
    ),
    resolution_evidence=("job.source_ats in {greenhouse,lever,ashby}",),
)

_R_STRUCTURED_ATS_FORM = RouteSpec(
    type=RouteType.STRUCTURED_ATS_FORM,
    automation_level=AutomationLevel.ASSISTED,
    submission_permitted=True,
    required_candidate_actions=(
        "Grant per-application submission authorization.",
        "Review pre-filled structured form; correct any low-"
        "confidence field.",
        "Click Send on the previewed packet.",
    ),
    limitations=(
        "Auto-submit locked behind the >99% form-map accuracy gate; "
        "assisted-only until unlock.",
        "Employer-side custom questions rendered in preview, never "
        "answered from an inference.",
    ),
    approval_requirement="per_application_authorization_scope",
    authorization_expiry_hint="24h after packet preview",
    expected_receipt=(
        "signed_submission_receipt: {external_ref, submitted_at, "
        "form_map_version, evidence_hash}"
    ),
    resolution_evidence=(
        "job.source_ats in {workday,taleo,icims,successfactors}",
    ),
)

_R_UNSTRUCTURED_WEB_FORM = RouteSpec(
    type=RouteType.UNSTRUCTURED_WEB_FORM,
    automation_level=AutomationLevel.MANUAL,
    submission_permitted=True,
    required_candidate_actions=(
        "Open the packet preview (template only, not a submission).",
        "Copy the tailored answers into the employer's form.",
        "Log the submission (or leave the outcome autopilot to "
        "detect it).",
    ),
    limitations=(
        "No auto-submit under any circumstance — no structured "
        "contract to bind against.",
        "No CAPTCHA or auth bypass; the candidate uses their own "
        "browser session.",
    ),
    approval_requirement="template_preview_authorization",
    authorization_expiry_hint="7d for template validity",
    expected_receipt=(
        "candidate_reported_receipt: {submitted_at_asserted, "
        "screenshot_hash?}"
    ),
    resolution_evidence=(
        "apply_url points to employer-owned domain with no "
        "recognized ATS signature",
    ),
)

_R_EMAIL_SUBMISSION = RouteSpec(
    type=RouteType.EMAIL_SUBMISSION,
    automation_level=AutomationLevel.MANUAL,
    submission_permitted=True,
    required_candidate_actions=(
        "Grant own-mailbox consent (Gmail/Outlook OAuth) for the "
        "specific email.",
        "Approve the drafted email + attachments per send.",
    ),
    limitations=(
        "Never sends from the platform domain — reputation lives on "
        "the candidate's account.",
        "Provider-rate-limited; abuse rules honored.",
    ),
    approval_requirement="own_mailbox_send_authorization",
    authorization_expiry_hint="per-send explicit approval, no bulk grant",
    expected_receipt=(
        "own_mailbox_send_receipt: {message_id, sent_at, provider}"
    ),
    resolution_evidence=("apply_email is set OR apply_url is a mailto:",),
)

_R_FEDERAL_PORTAL = RouteSpec(
    type=RouteType.FEDERAL_PORTAL,
    automation_level=AutomationLevel.MANUAL,
    submission_permitted=True,
    required_candidate_actions=(
        "Confirm US-person / hiring-path eligibility on the posting "
        "(federal rules).",
        "Follow the deep link to USAJOBS and complete the "
        "government-side submission personally.",
        "Confirm submission back to the platform to attach the "
        "evidence receipt.",
    ),
    limitations=(
        "Automation forbidden — federal posting terms.",
        "Platform never handles the candidate's federal login.",
    ),
    approval_requirement="federal_route_acknowledgment",
    authorization_expiry_hint="per-application acknowledgment",
    expected_receipt=(
        "candidate_reported_receipt: {portal_reference, submitted_at}"
    ),
    resolution_evidence=("job.source_ats == 'usajobs'",),
)

_R_PARTNER_REFERRAL = RouteSpec(
    type=RouteType.PARTNER_REFERRAL,
    automation_level=AutomationLevel.ASSISTED,
    submission_permitted=True,
    required_candidate_actions=(
        "Approve the intro packet contents (visible to the intro "
        "partner).",
        "Choose the intro partner from the candidate's warm-intro "
        "graph.",
    ),
    limitations=(
        "No cold outreach — only paths with an existing consented "
        "partner edge.",
        "Partner acts as the human of record for the referral.",
    ),
    approval_requirement="warm_intro_scope_consent",
    authorization_expiry_hint="until candidate revokes",
    expected_receipt=(
        "intro_receipt: {partner_id, intro_sent_at, message_hash}"
    ),
    resolution_evidence=(
        "opportunity has a resolved partner_edge OR a referrer "
        "context is set on the request",
    ),
)

_R_NO_APPLY_PATH = RouteSpec(
    type=RouteType.NO_APPLY_PATH,
    automation_level=AutomationLevel.UNPERMITTED,
    submission_permitted=False,
    required_candidate_actions=(
        "Review the platform-prepared packet.",
        "Follow the employer's out-of-band process personally.",
    ),
    limitations=(
        "No submission surface exists on this posting; the platform "
        "prepares, it does not send.",
        "Autopilot will not attempt a send.",
    ),
    approval_requirement="preparation_only",
    authorization_expiry_hint="not applicable — no send occurs",
    expected_receipt=(
        "preparation_receipt: {packet_id, prepared_at}"
    ),
    resolution_evidence=(
        "apply_url absent OR marked deep-link-only OR employer "
        "policy blocks structured submission",
    ),
)


ROUTE_REGISTRY: Final[dict[RouteType, RouteSpec]] = {
    r.type: r for r in (
        _R_DIRECT_ATS_API,
        _R_STRUCTURED_ATS_FORM,
        _R_UNSTRUCTURED_WEB_FORM,
        _R_EMAIL_SUBMISSION,
        _R_FEDERAL_PORTAL,
        _R_PARTNER_REFERRAL,
        _R_NO_APPLY_PATH,
    )
}


# ==================================================================
# Resolver — deterministic classifier
# ==================================================================
_DIRECT_ATS_KEYS = frozenset({"greenhouse", "lever", "ashby"})
_STRUCTURED_ATS_KEYS = frozenset({
    "workday", "taleo", "icims", "successfactors",
})
_FEDERAL_KEYS = frozenset({"usajobs"})


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _is_mailto_url(url: str | None) -> bool:
    if not url:
        return False
    return _norm(url).startswith("mailto:")


def _apply_url_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return urlparse(url).hostname
    except Exception:
        return None


def resolve_route(opportunity: dict[str, Any]) -> RouteSpec:
    """Deterministically resolve an opportunity to exactly one
    `RouteSpec`.

    Resolution order (rail: bias toward LESS automation on ambiguity):

      1. `partner_edge` context → PARTNER_REFERRAL.
      2. `source_ats == 'usajobs'` → FEDERAL_PORTAL.
      3. mailto: apply_url OR non-empty `apply_email` → EMAIL_SUBMISSION.
      4. `source_ats in DIRECT_ATS` AND non-empty apply_url →
         DIRECT_ATS_API.
      5. `source_ats in STRUCTURED_ATS` → STRUCTURED_ATS_FORM.
      6. apply_url present (any other host) → UNSTRUCTURED_WEB_FORM.
      7. otherwise → NO_APPLY_PATH.

    Notes:
      * Every branch consults only fields the canonical opportunity
        model already carries (P1 Batch 3). No new data required.
      * The `partner_edge` clause makes PARTNER_REFERRAL a first-class
        override so a curated intro path wins over the ATS API.
      * A DIRECT_ATS_API adapter row without an `apply_url` falls
        through to NO_APPLY_PATH — the platform never fabricates a
        submission target.
    """
    if opportunity.get("partner_edge"):
        return ROUTE_REGISTRY[RouteType.PARTNER_REFERRAL]

    source = _norm(opportunity.get("source_ats"))
    apply_url = opportunity.get("apply_url")
    apply_email = _norm(opportunity.get("apply_email"))

    if source in _FEDERAL_KEYS:
        return ROUTE_REGISTRY[RouteType.FEDERAL_PORTAL]

    if _is_mailto_url(apply_url) or apply_email:
        return ROUTE_REGISTRY[RouteType.EMAIL_SUBMISSION]

    if source in _DIRECT_ATS_KEYS and apply_url:
        return ROUTE_REGISTRY[RouteType.DIRECT_ATS_API]

    if source in _STRUCTURED_ATS_KEYS:
        return ROUTE_REGISTRY[RouteType.STRUCTURED_ATS_FORM]

    if apply_url and _apply_url_host(apply_url):
        return ROUTE_REGISTRY[RouteType.UNSTRUCTURED_WEB_FORM]

    return ROUTE_REGISTRY[RouteType.NO_APPLY_PATH]


def get_spec(route_type: RouteType | str) -> RouteSpec:
    """Public lookup — strict on unknown type."""
    if isinstance(route_type, str):
        route_type = RouteType(route_type)
    return ROUTE_REGISTRY[route_type]
