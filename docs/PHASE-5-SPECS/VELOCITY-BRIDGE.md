# VELOCITY-BRIDGE.md — SPEC-ONLY (Phase 5)

**Status:** SPEC. Build nothing. Do not register routes. Do not write tests.

## Intent
Bridge from "user just sealed eligibility" → "user has 5 draft applications ready to review" in one continuous flow, without asking the user to hunt for buttons. Reduces first-value time from N clicks → 2 clicks.

## Hard rails (locked)
- Consent-gated: `discover_jobs` + `generate_materials` + `submit_applications` MUST all be granted BEFORE the bridge fires. Missing any → surface which consent is missing + link to grant.
- Ceiling: 5 draft applications. Beyond that, the user must Approve first.
- Every generation goes through the standard grounding firewall (same as 5d).
- Dry-run posture: bridge only generates DRAFTS. Never auto-sends, never auto-submits.
- Idempotent: re-triggering the bridge within 24h returns the existing 5 drafts, never a new 5 on top.

## Public surface (spec)
- `POST /api/v1/velocity-bridge/start` → `{drafts_created, existing_drafts_reused, consents_missing, ready_for_review}`.
- `GET /api/v1/velocity-bridge/status` → same shape without side-effects.

## Storage (spec)
- New collection `velocity_bridge_runs`: `{id, user_id, started_at, drafts_created, existing_drafts_reused, terminal_state}`.

## Open questions (defer)
- Should the bridge auto-attach material variants (5b A/B)? Founder decision required.
- Should it prefer employers with the responds-fast badge (5e)? Trade-off between "user's target roles" and "fastest responders".

## Anti-goals (locked)
- NEVER a "one-tap apply" — the ceiling is DRAFTS, not sends.
- NEVER surface a job the user has hidden or previously rejected.
