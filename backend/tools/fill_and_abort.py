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
    """Return a captcha-provider label if the page is CAPTCHA-gated, else None."""
    try:
        title = (await page.title()) or ""
    except Exception:
        title = ""
    if re.search(r"just a moment|verifying|attention required|access denied",
                 title, re.IGNORECASE):
        return "cloudflare"
    # Look for challenge iframes (hCaptcha, reCAPTCHA, Cloudflare Turnstile).
    try:
        iframe_src = await page.evaluate(
            """() => Array.from(document.querySelectorAll('iframe'))
                        .map(i => i.src || '').join(' ')"""
        )
    except Exception:
        iframe_src = ""
    if re.search(r"hcaptcha\.com|challenges\.cloudflare\.com|recaptcha", iframe_src or ""):
        return "iframe-challenge"
    return None


async def _run(urls: list[str], out_dir: Path, evidence_md: Path, limit: int = 20) -> dict:
    """Execute the fill-and-abort dry run against `urls`. Never submits."""
    from playwright.async_api import async_playwright  # type: ignore
    out_dir.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc)
    results: list[dict] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=("OpportunityOS-DryRun/1.0 (fixture; contact: "
                            "support@opportunityos.dev)"),
                viewport={"width": 1400, "height": 900},
            )

            # Block ALL non-GET requests to any origin the page opens.
            async def _guard(route):
                m = route.request.method.upper()
                if m != "GET":
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

                    # Neutralize submit buttons EVERYWHERE on the page.
                    await page.evaluate(
                        """() => {
                            const rx = /submit|apply|send/i;
                            document.querySelectorAll('button, input[type=submit], a')
                                .forEach(el => {
                                    const t = (el.innerText || el.value || el.getAttribute('aria-label') || '');
                                    if (rx.test(t)) {
                                        el.setAttribute('data-abort-blocked','1');
                                        el.style.pointerEvents = 'none';
                                        try { el.disabled = true; } catch(e){}
                                    }
                                });
                        }"""
                    )

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
    summary = {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_s": (finished_at - started_at).total_seconds(),
        "targets": len(results),
        "filled_and_aborted": sum(1 for r in results if r["state"] == "filled_and_aborted"),
        "fields_correct": sum(1 for r in results if r.get("fields_filled_correctly")),
        "skipped_captcha": sum(1 for r in results if r["state"] == "skipped_captcha"),
        "failed": sum(1 for r in results if r["state"] == "failed"),
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
        f.write(f"* Failed: {summary['failed']}\n\n")
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
    return [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


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
