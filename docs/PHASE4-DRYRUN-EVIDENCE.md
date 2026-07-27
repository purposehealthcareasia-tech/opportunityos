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

## Dry-run pass 2026-07-27T21:54:29.348148+00:00

* Elapsed: 55.03s
* Targets: 20
* Filled + aborted: 3
* Fields-correct (email + name filled): 0
* Skipped-CAPTCHA: 17
* Failed: 0

| # | URL | State | HTTP | Fields found | Fields filled | Correct | CAPTCHA | Screenshot |
|---|-----|-------|------|--------------|---------------|---------|---------|------------|
| 00 | `https://job-boards.greenhouse.io/ionq/jobs/6005910004  # IonQ - Chief Architect - Optical Communication Terminals` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_00_captcha.png` |
| 01 | `https://job-boards.greenhouse.io/whisperaero/jobs/5323857008  # Whisper Aero - Business Development Manager, Defense` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_01_captcha.png` |
| 02 | `https://boards.greenhouse.io/lightmatter/jobs/4838692008?gh_jid=4838692008  # Lightmatter - Analog IC Design Engineer, AMS` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_02_captcha.png` |
| 03 | `https://boards.greenhouse.io/robinhood/jobs/6669758?t=gh_src=&gh_jid=6669758  # Robinhood - Android Engineer, Government Products` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_03_captcha.png` |
| 04 | `https://boards.greenhouse.io/relativity/jobs/8639195002?gh_jid=8639195002  # Relativity Space - Accounting Generalist` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_04_captcha.png` |
| 05 | `https://boards.greenhouse.io/faire/jobs/8601430002?gh_jid=8601430002  # Faire - Account Executive` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_05_captcha.png` |
| 06 | `https://job-boards.greenhouse.io/tenstorrent/jobs/5055233007  # Tenstorrent - Acceleration Kernel Developer Lead` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_06_captcha.png` |
| 07 | `https://job-boards.greenhouse.io/momentus/jobs/6004816004  # Momentus - Additive Manufacturing Product Manager` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_07_captcha.png` |
| 08 | `https://job-boards.greenhouse.io/kodiak/jobs/4327498009  # Kodiak Robotics - Accounting Manager` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_08_captcha.png` |
| 09 | `https://job-boards.greenhouse.io/discord/jobs/8433948002  # Discord - Account Executive - Tech` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_09_captcha.png` |
| 10 | `https://boards.greenhouse.io/spacex/jobs/8643277002?gh_jid=8643277002  # SpaceX - Accountant` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_10_captcha.png` |
| 11 | `https://boards.greenhouse.io/vast/jobs/4694238006?gh_jid=4694238006  # Vast Space - 2026 Fall Internship - Manufacturing` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_11_captcha.png` |
| 12 | `https://boards.greenhouse.io/redwoodmaterials/jobs/5894704004?gh_jid=5894704004  # Redwood Materials - Abuse Test Engineer, Energy Storage` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_12_captcha.png` |
| 13 | `https://job-boards.greenhouse.io/betterhelp/jobs/4234786009  # BetterHelp - Clinical Psychologist- Remote` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_13_captcha.png` |
| 14 | `https://job-boards.greenhouse.io/lucidmotors/jobs/5151086007  # Lucid Motors - Assembly Team Lead` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_14_captcha.png` |
| 15 | `https://boards.greenhouse.io/figma/jobs/5364702004?gh_jid=5364702004  # Figma - Account Executive, Emerging Enterprise (Berlin, Germany)` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_15_captcha.png` |
| 16 | `https://job-boards.greenhouse.io/rocketlab/jobs/7763159003  # Rocket Lab - Accounts Payables Specialist` | skipped_captcha | 200 | 0 | 0 | no | iframe-challenge | `/app/docs/dryrun-screenshots/dryrun_16_captcha.png` |
| 17 | `https://jobs.lever.co/wealthfront/78d6f6d5-1f08-4d5d-87be-c4250567bfb5/apply  # Wealthfront - Android Engineer` | filled_and_aborted | 404 | 0 | 0 | no | - | `/app/docs/dryrun-screenshots/dryrun_17.png` |
| 18 | `https://jobs.lever.co/shieldai/41468aca-c1c2-4a7b-aec8-f499e64b6d1e/apply  # Shield AI - Aerostructures Design Engineer II (R4953)` | filled_and_aborted | 404 | 0 | 0 | no | - | `/app/docs/dryrun-screenshots/dryrun_18.png` |
| 19 | `https://jobs.lever.co/loftorbital/0d2134a5-e7da-4787-a1fa-4bd4d6d92685/apply  # Loft Orbital - Attitude Guidance & Performance Engineer` | filled_and_aborted | 404 | 0 | 0 | no | - | `/app/docs/dryrun-screenshots/dryrun_19.png` |

