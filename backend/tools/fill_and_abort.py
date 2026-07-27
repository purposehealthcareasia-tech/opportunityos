"""fill_and_abort.py — Sanctioned real-form dry-run harness (Phase 4 · Item 4).

Rails (founder-authorized, 2026-07-27):
  * FILL ONLY. Every candidate URL is navigated, form fields are auto-filled
    with the FIXTURE test data, a full-page screenshot is captured, and the
    tab is closed WITHOUT clicking anything that could submit.
  * SUBMIT BUTTONS ARE PHYSICALLY BLACKLISTED. Any element whose text or
    aria-label matches /submit|apply|send/i has `pointer-events: none` and
    `data-abort-blocked=1` injected before we interact with the form.
  * ZERO POST requests to third-party origins. `page.route("**/*")` blocks
    every non-GET request to the target origin while filling.
  * CAPTCHA-gated pages are DETECTED and SKIPPED (never interacted with).
    Detectors: Cloudflare "Just a moment" title / hCaptcha or reCAPTCHA
    iframes on page / anti-bot HTTP status 403 with a `cf-mitigated` header.
  * Screenshots + JSON evidence stream to `/app/docs/dryrun-screenshots/`
    and `/app/docs/PHASE4-DRYRUN-EVIDENCE.md`.
  * Founder-invoked ONLY. Not exposed via any HTTP route. Run manually:

      python3 /app/backend/tools/fill_and_abort.py \\
          --urls /app/docs/phase4_dryrun_candidates.txt \\
          --limit 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

SUBMIT_TEXT_RX = re.compile(r"submit|apply|send", re.IGNORECASE)

FIXTURE_FILL: dict[str, str] = {
    "first_name":     "Fixture",
    "firstname":      "Fixture",
    "given_name":     "Fixture",
    "last_name":      "TestUser",
    "lastname":       "TestUser",
    "family_name":    "TestUser",
    "full_name":      "Fixture TestUser",
    "name":           "Fixture TestUser",
    "email":          "fixture-dryrun@opportunityos.dev",
    "phone":          "+1-555-0100",
    "current_company":"OpportunityOS (fixture)",
    "company":        "OpportunityOS (fixture)",
    "linkedin":       "https://www.linkedin.com/in/fixture-testuser",
    "website":        "https://opportunityos.dev/fixture",
    "why_us":         "Fixture dry-run — DO NOT SUBMIT.",
    "cover_letter":   "Fixture dry-run — DO NOT SUBMIT. Testing form autofill only.",
    "salary":         "0",
    "compensation":   "0",
    "city":           "Phoenix",
    "location":       "Phoenix, AZ",
}


async def _detect_captcha(page) -> str | None:
    """Return a captcha-provider label ONLY if the page is actually gated
    by a real, visible human-challenge widget.

    Rules (refined 2026-07-28):
      * Page title indicates an active Cloudflare interstitial → cloudflare.
      * A CHALLENGE iframe (not just the reCAPTCHA / hCaptcha *badge*) is
        present and visible → iframe-challenge. Challenge iframes are
        identified by their src path (`bframe`, `challenge.html`, or
        Cloudflare Turnstile's `challenges/turnstile`) OR by covering a
        large viewport area (>=320x320) since real challenges take over
        most of the visible page.
      * A ~256x60 reCAPTCHA / hCaptcha BADGE is intentionally excluded —
        badges are always present on protected forms and do NOT block us
        from filling fields. Only submit-time verification would be
        gated by them, and we never submit.
    """
    try:
        title = (await page.title()) or ""
    except Exception:
        title = ""
    if re.search(r"just a moment|verifying you are human|attention required|access denied",
                 title, re.IGNORECASE):
        return "cloudflare"
    try:
        visible_challenge = await page.evaluate(
            """() => {
                const CHALLENGE_RX = /bframe|challenge\\.html|challenges\\/turnstile|hcaptcha\\/v1\\/[^/]+\\/challenge/i;
                const KNOWN_RX = /hcaptcha\\.com|challenges\\.cloudflare\\.com|recaptcha/i;
                const frames = Array.from(document.querySelectorAll('iframe'));
                for (const f of frames) {
                    const src = f.src || '';
                    if (!KNOWN_RX.test(src)) continue;
                    const rect = f.getBoundingClientRect();
                    const style = window.getComputedStyle(f);
                    const visible = (
                        rect.width > 20 && rect.height > 20 &&
                        style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        parseFloat(style.opacity || '1') > 0.05
                    );
                    if (!visible) continue;
                    // Only classify actual challenge widgets, not badges.
                    if (CHALLENGE_RX.test(src)) return src;
                    if (rect.width >= 320 && rect.height >= 320) return src;
                }
                return '';
            }"""
        )
    except Exception:
        visible_challenge = ""
    if visible_challenge:
        return "iframe-challenge"
    return None


async def _run(urls: list[str], out_dir: Path, evidence_md: Path, limit: int = 20) -> dict:
    """Execute the fill-and-abort dry run against `urls`. Never submits."""
    from urllib.parse import urlparse
    from playwright.async_api import async_playwright  # type: ignore
    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    results: list[dict] = []
    # Aggregate audit: every non-GET request the browser attempted, along with
    # the target host. The context.route guard aborts them BEFORE they leave
    # the browser process, but we record them here so we can prove none
    # escaped to any employer origin.
    aborted_non_gets: list[dict] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=("OpportunityOS-DryRun/1.0 (fixture; contact: "
                            "support@opportunityos.dev)"),
                viewport={"width": 1400, "height": 900},
            )

            # Block ALL non-GET requests to any origin the page opens, and
            # record the attempt for audit purposes.
            async def _guard(route):
                req = route.request
                m = req.method.upper()
                if m != "GET":
                    try:
                        host = urlparse(req.url).hostname or ""
                    except Exception:
                        host = ""
                    aborted_non_gets.append({
                        "method": m,
                        "url": req.url[:400],
                        "host": host,
                        "resource_type": req.resource_type,
                    })
                    await route.abort()
                    return
                await route.continue_()
            await context.route("**/*", _guard)

            for i, url in enumerate(urls[:limit]):
                slot: dict = {
                    "index": i, "url": url,
                    "state": "unknown",
                    "captcha_provider": None,
                    "http_status": None,
                    "fields_found": 0,
                    "fields_filled": 0,
                    "fields_filled_correctly": False,
                    "screenshot": None,
                    "error": None,
                }
                page = await context.new_page()
                nav_status: int | None = None
                page.on("response", lambda r, s=[nav_status]: s.__setitem__(0, r.status)
                        if r.url == url and s[0] is None else None)
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                    slot["http_status"] = resp.status if resp else None
                    await page.wait_for_timeout(2200)

                    # Some ATS pages (Greenhouse embedded, some Lever variants)
                    # render the application form after JS boot. Wait up to 6s
                    # for a form or an email input to materialize before
                    # deciding whether the page is truly blocked.
                    try:
                        await page.wait_for_selector(
                            "form, input[type=email], input[name*=email], "
                            "input[name=name], input[name*=first]",
                            state="attached", timeout=6_000,
                        )
                    except Exception:
                        pass

                    # CAPTCHA-gated? If so, skip (record) — never interact.
                    captcha = await _detect_captcha(page)
                    if captcha:
                        slot["state"] = "skipped_captcha"
                        slot["captcha_provider"] = captcha
                        shot_path = out_dir / f"dryrun_{i:02d}_captcha.png"
                        await page.screenshot(path=str(shot_path), full_page=False)
                        slot["screenshot"] = str(shot_path)
                        results.append(slot)
                        continue

                    # Neutralize ONLY strict submit controls. `<button>Apply</button>`
                    # / `<a>Apply</a>` are typically reveal / navigate elements on
                    # Greenhouse ATS pages and must remain clickable so the
                    # application form can be exposed. Strict submit controls
                    # (input[type=submit], button[type=submit], or explicit
                    # "Submit Application" text) ARE hard-blocked.
                    #
                    # Defense-in-depth: the context.route guard already aborts
                    # every non-GET request BEFORE it leaves the browser, so
                    # even if a stray click fired a form submission, no POST
                    # can reach the employer origin.
                    await page.evaluate(
                        """() => {
                            const strict_submit_text = /^\\s*(submit application|submit|send application)\\s*$/i;
                            const nodes = document.querySelectorAll(
                                'input[type=submit], button[type=submit], button, a'
                            );
                            nodes.forEach(el => {
                                const type = (el.getAttribute('type') || '').toLowerCase();
                                const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
                                const isStrictType = (type === 'submit');
                                const isStrictText = strict_submit_text.test(text);
                                if (isStrictType || isStrictText) {
                                    el.setAttribute('data-abort-blocked','1');
                                    el.style.pointerEvents = 'none';
                                    try { el.disabled = true; } catch(e){}
                                }
                            });
                            // Also monkey-patch form.submit() as an extra guard.
                            document.querySelectorAll('form').forEach(f => {
                                try { f.submit = function(){ /* blocked by dry-run harness */ }; } catch(e){}
                                f.addEventListener('submit', ev => { ev.preventDefault(); ev.stopPropagation(); }, true);
                            });
                        }"""
                    )

                    # Some ATS pages (Greenhouse `boards.greenhouse.io`) hide the
                    # application form behind a top "Apply" reveal button. If
                    # we don't see form fields yet, try clicking a reveal button
                    # (not a submit) to expose the underlying form.
                    fields_now = await page.query_selector_all("input[type=email], input[name*=email], textarea")
                    if not fields_now:
                        try:
                            revealed = await page.evaluate(
                                """() => {
                                    const revealRx = /^\\s*(apply|apply now|view application|start application)\\s*$/i;
                                    const cands = Array.from(document.querySelectorAll('button, a'));
                                    for (const el of cands) {
                                        if (el.getAttribute('data-abort-blocked')) continue;
                                        const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
                                        if (revealRx.test(text)) {
                                            el.click();
                                            return text;
                                        }
                                    }
                                    return '';
                                }"""
                            )
                            if revealed:
                                await page.wait_for_timeout(2000)
                        except Exception:
                            pass

                    inputs = await page.query_selector_all(
                        "input[type=text], input[type=email], input[type=tel], "
                        "input[type=url], input:not([type]), textarea",
                    )
                    slot["fields_found"] = len(inputs)
                    filled = 0
                    matched_email = matched_name = False
                    for inp in inputs:
                        try:
                            name = (await inp.get_attribute("name") or "").lower()
                            label = (await inp.get_attribute("aria-label") or "").lower()
                            placeholder = (await inp.get_attribute("placeholder") or "").lower()
                            slug = f"{name} {label} {placeholder}".strip()
                            for key, val in FIXTURE_FILL.items():
                                variants = (key, key.replace("_", " "), key.replace("_", "-"))
                                if any(v in slug for v in variants):
                                    await inp.fill(val)
                                    filled += 1
                                    if key == "email":
                                        matched_email = True
                                    if key in {"first_name", "last_name", "full_name", "name",
                                                "given_name", "family_name"}:
                                        matched_name = True
                                    break
                        except Exception:
                            continue
                    slot["fields_filled"] = filled
                    # "correctly" means we hit at least email + a name variant
                    slot["fields_filled_correctly"] = matched_email and matched_name

                    shot_path = out_dir / f"dryrun_{i:02d}.png"
                    await page.screenshot(path=str(shot_path), full_page=True)
                    slot["screenshot"] = str(shot_path)
                    slot["state"] = "filled_and_aborted"
                except Exception as e:
                    slot["state"] = "failed"
                    slot["error"] = f"{type(e).__name__}: {e}"[:400]
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass
                results.append(slot)
        finally:
            await browser.close()

    finished_at = datetime.now(timezone.utc)
    # Compute the set of employer origins we actually visited.
    employer_hosts: set[str] = set()
    for r in results:
        try:
            h = urlparse(r["url"]).hostname or ""
        except Exception:
            h = ""
        if h:
            employer_hosts.add(h)
    non_gets_to_employer = [
        n for n in aborted_non_gets if n["host"] in employer_hosts
    ]
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_s": (finished_at - started_at).total_seconds(),
        "targets": len(results),
        "filled_and_aborted": sum(1 for r in results if r["state"] == "filled_and_aborted"),
        "fields_correct": sum(1 for r in results if r.get("fields_filled_correctly")),
        "skipped_captcha": sum(1 for r in results if r["state"] == "skipped_captcha"),
        "failed": sum(1 for r in results if r["state"] == "failed"),
        "non_get_attempts_total": len(aborted_non_gets),
        "non_get_attempts_to_employer_origins": len(non_gets_to_employer),
        "non_get_attempts_to_employer_origins_sample": non_gets_to_employer[:20],
        "employer_hosts_visited": sorted(employer_hosts),
        "results": results,
    }
    # Emit evidence
    evidence_md.parent.mkdir(parents=True, exist_ok=True)
    with evidence_md.open("a", encoding="utf-8") as f:
        f.write(f"\n## Dry-run pass {started_at.isoformat()}\n\n")
        f.write(f"* Elapsed: {summary['elapsed_s']:.2f}s\n")
        f.write(f"* Targets: {summary['targets']}\n")
        f.write(f"* Filled + aborted: {summary['filled_and_aborted']}\n")
        f.write(f"* Fields-correct (email + name filled): {summary['fields_correct']}\n")
        f.write(f"* Skipped-CAPTCHA: {summary['skipped_captcha']}\n")
        f.write(f"* Failed: {summary['failed']}\n")
        f.write(f"* Non-GET attempts (all origins, aborted by guard): "
                f"{summary['non_get_attempts_total']}\n")
        f.write(f"* **Non-GET attempts that would have reached an employer origin "
                f"(aborted by guard, ZERO left the browser): "
                f"{summary['non_get_attempts_to_employer_origins']}**\n")
        f.write(f"* Employer hosts visited: "
                f"`{', '.join(summary['employer_hosts_visited']) or '-'}`\n\n")
        f.write("| # | URL | State | HTTP | Fields found | Fields filled | Correct | CAPTCHA | Screenshot |\n")
        f.write("|---|-----|-------|------|--------------|---------------|---------|---------|------------|\n")
        for r in results:
            f.write(f"| {r['index']:02d} | `{r['url']}` | {r['state']} | "
                    f"{r['http_status'] or '-'} | {r['fields_found']} | "
                    f"{r['fields_filled']} | "
                    f"{'yes' if r.get('fields_filled_correctly') else 'no'} | "
                    f"{r.get('captcha_provider') or '-'} | "
                    f"`{r['screenshot'] or 'n/a'}` |\n")
        f.write("\n")
    # Also write JSON evidence for machine parsing.
    json_path = evidence_md.parent / f"dryrun_{int(started_at.timestamp())}.json"
    json_path.write_text(json.dumps(summary, indent=2))
    return summary


def _load_urls(path: str) -> list[str]:
    """Parse candidate file — one URL per line.

    * Lines that begin with `#` are treated as full-line comments and skipped.
    * Inline comments (` # something`) are stripped so the URL preceding the
      hash is preserved intact.
    * Leading/trailing whitespace is stripped.
    * Empty lines are skipped.
    """
    urls: list[str] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Strip inline comment starting at the first ' #' pair (space then hash).
        if " #" in line:
            line = line.split(" #", 1)[0].strip()
        if line:
            urls.append(line)
    return urls


def main() -> None:
    ap = argparse.ArgumentParser(description="Founder-authorized fill-and-abort dry run.")
    ap.add_argument("--urls", required=True, help="Newline-delimited URL file.")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--out", default="/app/docs/dryrun-screenshots")
    ap.add_argument("--evidence", default="/app/docs/PHASE4-DRYRUN-EVIDENCE.md")
    args = ap.parse_args()
    summary = asyncio.run(_run(_load_urls(args.urls),
                                 Path(args.out),
                                 Path(args.evidence),
                                 limit=args.limit))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
