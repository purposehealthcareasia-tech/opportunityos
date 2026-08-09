# WARM-INTRO-FINDER.md — SPEC-ONLY (Phase 5)

**Status:** SPEC. Build nothing. Do not register routes. Do not write tests.

## Intent
Given a target employer, surface a list of "warm connections" the user might reach out to. NEVER by scraping LinkedIn; only from user-approved sources.

## Hard rails (locked)
- **Zero scraping.** Data sources are limited to: (a) user-uploaded contact CSV (explicit consent scope `import_contacts`, not yet defined), (b) user-approved OAuth into Gmail/Google Contacts (documented separately), (c) manually-added connections in the Fynd app.
- Consent-scoped: new scope `warm_intro_search` (spec — add to `core/policy.py` when built).
- User-scoped only: warm-intro suggestions NEVER cross users. Fynd never says "your friend of a friend Alice works at Acme" derived from Bob's connections.
- No automated outreach. The suggestion surface produces a name + relationship type + last-contact date; the user copies the info manually or clicks a mailto: link that opens THEIR OWN mail client.

## Public surface (spec)
- `GET /api/v1/warm-intro/search?employer_key=...` → `{suggestions: [{name, relationship, last_contact_at, source}], count, sources_available}`.

## Anti-goals (locked)
- NEVER contact anyone on the user's behalf.
- NEVER cross the user boundary. Bob's Alice is Bob's, not the platform's.
- NEVER surface a LinkedIn-derived signal (scraping violates ToS; no signal is worth the rail).
