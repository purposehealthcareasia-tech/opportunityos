# A2A-PROTOCOL.md — SPEC-ONLY (Phase 5)

**Status:** SPEC. Build nothing. Do not register routes. Do not write tests.

## Intent
Agent-to-Agent protocol: define the wire format by which two Fynd-shaped agents (candidate-side and employer-side) can exchange consent-scoped Passport data, application state, and outcome events over signed HTTP.

## Design goals
1. **Interoperability** — any implementation that speaks the spec, not just Fynd's, can consume and produce data.
2. **Consent-first** — every A2A call carries an explicit consent-scope token (see 5i Passport-as-API pattern).
3. **Auditability** — every A2A call receipts on both sides.
4. **No side-channels** — no message can transmit fields the token's scope doesn't authorize (server-side filter is the source of truth).

## Wire format (spec)
```
POST /a2a/v1/exchange
Authorization: Bearer <per-scope token from Passport-as-API v1>
Content-Type: application/json

{
  "action": "passport_read" | "application_status_push" | "outcome_event_push",
  "audience": "<opaque agent identifier>",
  "payload": { ... action-specific ... }
}
```

## Actions (spec)
- `passport_read` — third-party (employer's agent) reads a filtered Passport. Same filter engine as 5a Share Link + 5i Passport-as-API.
- `application_status_push` — employer's agent notifies candidate's agent that an application state changed (received → under review → interview scheduled → offer / rejection).
- `outcome_event_push` — arrival triggers 5f-style receipt mint on the candidate side.

## Verification
- Same signature spec as 5f (HMAC-SHA256, canonical serialization).
- Both sides log to their local receipt collection.

## Hard rails (locked)
- NEVER auto-executes on receipt. Every push arrives as a proposed event; the candidate must click to accept.
- Rate-limit + abuse-log on the A2A endpoint (same pattern as `/employers/connect`).
- Rejection reasons standardized: `not_a_fit`, `role_closed`, `budget_change`, `other`. NEVER free-text on rejection (avoids demographic bias signals).

## Anti-goals (locked)
- NOT an ATS. Fynd is not competing with Greenhouse.
- NOT a replacement for the candidate's inbox. It's a signed side-channel with structured payloads.
- NEVER carries payment / offer-letter documents. Those are separate legal surfaces.

## Open questions (defer)
- Federation model: pairwise trust bootstrap (spec) vs. central directory (avoid).
- Revocation propagation: when a user revokes a 5i token, how does the employer's agent learn? (Sync poll? Webhook? Both?)
