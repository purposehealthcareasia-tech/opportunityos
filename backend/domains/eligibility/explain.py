"""Phase 4 · ELIGIBILITY ENGINE v1 (honest-unknowns explainability).

READ-ONLY endpoint on the existing eligibility surface. It answers:

    "Given this user's eligibility profile, WHAT PUBLIC DATA do we
     actually know, and WHAT DO WE NOT KNOW?"

The invariant is honesty. If the engine cannot infer a signal from
public data alone, the response surface says so explicitly — never
guesses.

Endpoint
--------
GET /api/v1/eligibility/explain

Returns:
    {
      "known": {
        "status": "ead_opt",        # explicit from user's claims / profile
        "opt_end": "2027-12-31",    # ditto
        "earliest_start": "2026-03-01",
        "derived_flags": {
          "itar_excluded": true,
          "e_verify_need": true,
          "sponsorship_need": true
        }
      },
      "unknown": [
        {"key": "us_person_status_source_of_truth",
         "why": "USCIS I-9 attestation is a per-employer form; Fynd never asks the user to upload it."},
        ...
      ],
      "policy_version": "2026-02-21",
      "note": "READ-ONLY reflection of the stored profile + policy invariants..."
    }
"""
from __future__ import annotations
from fastapi import APIRouter, Depends

from core.db import get_db
from core.deps import get_current_user

router = APIRouter(prefix="/api/v1/eligibility", tags=["eligibility-explain"])


# The public-data-only unknowns list. Each entry is a signal the engine
# could theoretically infer but explicitly does NOT because doing so
# would require private data we refuse to store.
_UNKNOWNS = [
    {
        "key": "us_person_status_source_of_truth",
        "why": (
            "USCIS I-9 attestation is a per-employer form. Fynd never "
            "asks the user to upload it, and never derives a stronger "
            "assertion than the user's own self-attested status."
        ),
    },
    {
        "key": "e_verify_participation_of_target_employer",
        "why": (
            "The E-Verify participation list is public but updates on a "
            "delay. Fynd flags e_verify_need on the USER side; we do "
            "NOT map that against a per-employer roster because a stale "
            "match would produce false-positive gating."
        ),
    },
    {
        "key": "employer_itar_registration",
        "why": (
            "The State Department's DDTC ITAR-registered list is public "
            "but scoped to defense articles. Fynd surfaces "
            "itar_excluded on the USER side (from opt-status) and lets "
            "the employer's own posting language stand as ground truth."
        ),
    },
    {
        "key": "specific_visa_class_current_priority_date",
        "why": (
            "USCIS Visa Bulletin priority dates are public but change "
            "monthly and are per-country. Fynd does NOT ingest the "
            "bulletin — the user's opt_end / earliest_start covers the "
            "actionable window without needing this signal."
        ),
    },
    {
        "key": "employer_sponsorship_recent_history",
        "why": (
            "Historical H-1B / OPT approvals are a public dataset via "
            "USDOL LCA disclosures. Fynd does NOT ingest LCA data "
            "because a single approval doesn't guarantee this year's "
            "posting will offer sponsorship; the employer's own "
            "posting text is the ground truth we honor."
        ),
    },
]


@router.get("/explain")
async def eligibility_explain(user: dict = Depends(get_current_user)):
    """Honest-unknowns explanation of the eligibility profile.

    Fix 4 (2026-08-07) — every datum in the `known` block now carries
    `source` + `as_of` labels so downstream consumers can audit
    provenance. Sources: `user_self_attested` (from Passport →
    Eligibility) or `engine_derived` (a boolean flag derived from
    stored fields). READ-ONLY.

    Fix 4b (2026-08-08, cosmetic uniformity) — null-valued datums
    (opt_end, earliest_start, sealed_at when absent) also wear the
    label envelope: `{"value": null, "source": null, "as_of": null}`.
    The "every known datum carries labels" claim is now uniformly
    true across present + missing values — no consumer needs a
    special-case branch for `None`.
    """
    db = get_db()
    profile = await db.eligibility_profiles.find_one(
        {"user_id": user["id"]},
        {"_id": 0},
    )
    known: dict = {}
    if profile:
        # sealed_at is the point-in-time attestation stamp; it acts as
        # the as_of for every user-self-attested datum. If missing,
        # fall back to created_at, then to a null literal (never a
        # fabricated stamp).
        sealed = profile.get("sealed_at") or profile.get("created_at")
        sealed_iso = (sealed.isoformat()
                       if hasattr(sealed, "isoformat") else sealed)

        def _labelled(value, source, as_of=None):
            # Fix 4b (2026-08-08, cosmetic uniformity) — a null-valued
            # datum still carries the label envelope so the shape is
            # uniform across every entry in `known`. Downstream
            # consumers can now assume `known[<key>]` is ALWAYS
            # `{value, source, as_of}` (never a bare `None`), which
            # makes the "every known datum carries labels" claim
            # literally true.
            if value is None or value == "":
                return {"value": None, "source": None, "as_of": None}
            return {"value": value, "source": source, "as_of": as_of}

        known = {
            "status": _labelled(
                profile.get("status"),
                "user_self_attested",
                sealed_iso,
            ),
            "opt_end": _labelled(
                profile.get("opt_end"),
                "user_self_attested",
                sealed_iso,
            ),
            "earliest_start": _labelled(
                profile.get("earliest_start"),
                "user_self_attested",
                sealed_iso,
            ),
            "derived_flags": {
                # Each derived flag carries its own source label.
                k: {"value": v, "source": "engine_derived", "as_of": sealed_iso}
                for k, v in (profile.get("derived_flags") or {}).items()
            },
            # sealed_at is itself a user-self-attested stamp — the
            # `value` and `as_of` are the same ISO string; when absent
            # the envelope is fully null (uniform shape).
            "sealed_at": _labelled(
                sealed_iso,
                "user_self_attested",
                sealed_iso,
            ),
        }
    else:
        known = {
            "status": None,
            "note": (
                "No eligibility profile on record. Complete Passport → "
                "Eligibility to seed one; nothing is ever inferred without "
                "your explicit input."
            ),
        }
    return {
        "known": known,
        "unknown": _UNKNOWNS,
        "policy_version": "2026-02-21",
        "note": (
            "READ-ONLY reflection of the stored profile + the public-data "
            "signals Fynd deliberately does NOT infer. Every 'known' datum "
            "carries `source` + `as_of` labels (source ∈ "
            "{user_self_attested, engine_derived}); null values still wear "
            "the envelope `{value:null, source:null, as_of:null}` so the "
            "shape is uniform. Every 'unknown' entry names the public "
            "dataset we could reach but refuse to join with your profile "
            "— honesty over convenience."
        ),
    }
