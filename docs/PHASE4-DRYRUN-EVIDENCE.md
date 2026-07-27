# Phase 4 · Item 4 — Fill-and-Abort Real-Form Dry-Run Evidence

Founder-authorized: **fill-only. zero submits. zero POSTs to third-party origins.**

## Rails held by the harness (`backend/tools/fill_and_abort.py`)

1. Every submit-shaped element (`button`, `input[type=submit]`, `a` matching `/submit|apply|send/i`) is neutralized before any interaction — `pointer-events: none`, `disabled=true`, and a marker attribute `data-abort-blocked=1` is injected via `page.evaluate()`.
2. `context.route("**/*")` intercepts every request. Anything that isn't a plain `GET` is `abort()`-ed. **No form POSTs can leave the browser** even if a stray click occurred.
3. Fixture identity (`Fixture TestUser`, `fixture-dryrun@opportunityos.dev`, `+1-555-0100`) is the ONLY autofill data. No real candidate PII.
4. Each URL is opened in a fresh `context.new_page()`; screenshots are saved to `/app/docs/dryrun-screenshots/dryrun_NN.png`.
5. The harness is founder-invoked ONLY via CLI. There is no HTTP route that triggers it.

## Sanctioned candidate list

Candidate URLs are exported from the discovery corpus (public Greenhouse / Lever / Ashby endpoints) by the founder or admin. Format: newline-delimited plain-text URL file.

```
# One URL per line. Comments allowed.
https://boards.greenhouse.io/example/jobs/1234567
https://jobs.lever.co/example/abcdef12-3456-7890-abcd-ef1234567890
https://jobs.ashbyhq.com/example/00000000-0000-0000-0000-000000000000
```

Save to `/app/docs/phase4_dryrun_candidates.txt` and invoke:

```bash
python3 /app/backend/tools/fill_and_abort.py \
    --urls /app/docs/phase4_dryrun_candidates.txt \
    --limit 20
```

Evidence is appended to this file per pass. Screenshots land in `/app/docs/dryrun-screenshots/`.

---

## Passes

_(No passes have been executed yet. Evidence appears here after `python3 fill_and_abort.py` runs.)_
