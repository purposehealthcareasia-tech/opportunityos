# NEGOTIATION-COPILOT.md — SPEC-ONLY (Phase 5)

**Status:** SPEC. Build nothing. Do not register routes. Do not write tests.

## Intent
Post-offer: help the user prepare counter-offer talking points GROUNDED in their Passport (5d pattern) + market data (from public, non-scraped sources).

## Hard rails (locked)
- Grounding rule (from 5d) applies verbatim: no claim, no sentence. Every talking point must cite the source claim or the public market data row it references.
- Consent-scoped: new scope `negotiation_copilot` (spec).
- Market data source policy: ONLY use datasets we can legally ingest (BLS, Levels.fyi public CSVs, user-uploaded PDFs). NEVER scrape Glassdoor / LinkedIn / Blind.
- Output labeled "PRACTICE — you decide what to say." Never surfaces a script to send.
- NEVER surfaces a specific salary number as a "recommendation" — always describes the range and the sources.

## Public surface (spec)
- `POST /api/v1/negotiation/prep` → `{talking_points, market_data_cited, disclaimer}`.

## Storage (spec)
- New collection `negotiation_generations` (auditable trail, same shape as `interview_prep_generations`).

## Anti-goals (locked)
- NEVER produce a "here's what to write" script (that's crossing into agent-of-record territory).
- NEVER promise an outcome ("this will get you $180K").
- NEVER assume gender / race / age impact — the tool is grounded in the user's own claims + public rows, nothing else.
