# BACKGROUND-PRE-CLEARANCE.md — SPEC-ONLY (Phase 5)

**Status:** SPEC. Build nothing. Do not register routes. Do not write tests.

## Intent
Some employers require background checks before hire. Let the user PRE-CLEAR their record against common check types (education verification, employment verification, criminal-record self-attestation) so surprises don't appear post-offer.

## Hard rails (locked)
- **Consent + jurisdiction gate.** Background-check regulations differ by state (California vs. New York vs. Texas) and by check-type (ban-the-box, salary history bans, etc.). Every check surface MUST show the applicable rule for the user's state and let them opt IN, not opt OUT.
- No third-party integration in v0. Version 0 is USER SELF-ATTESTATION only. Later versions may integrate Checkr/HireRight — that requires a separate integration_playbook_expert_v2 pass + explicit user consent + data-sharing agreement disclosure.
- Consent-scoped: new scope `background_pre_clearance` (spec).
- All attestations HMAC-signed with `EVIDENCE_SIGNING_KEY` (same rails as 5f).
- Revocable. The user can retract any attestation and it flips the signed row to `state: "retracted"` (never deleted — audit trail).

## Public surface (spec)
- `POST /api/v1/background/attestations {kind, statement}` — mint signed self-attestation.
- `GET /api/v1/background/attestations` — list mine.
- `POST /api/v1/background/attestations/{id}/retract` — flip state, sign the retraction.

## Anti-goals (locked)
- NEVER runs an ACTUAL background check. That requires signed FCRA disclosure + adverse action process, out of scope for v0.
- NEVER promises "you'll pass". Pre-clearance is a self-attestation surface.
