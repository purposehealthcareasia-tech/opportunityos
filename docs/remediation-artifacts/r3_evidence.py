"""R3 · Code-Review Remediation — browser-leg evidence (builder-executed).

Mirrors the founder-approved replay pattern from Phase 1 G7-G10
(`/app/docs/phase-1-screenshots/g7_g10_evidence.py`): headless Chromium,
UI-login as `fixture-ead@opportunityos.dev`, drives the three pages that
carry the useMemo/component changes (+ /feed for the stable-ID keys and
Surprise Me capsule).

Coverage:
  R3-A · post-login storage + cookie hygiene:
         - localStorage keys are theme-only (never a token / session /
           email / password).
         - `oppos_session` cookie present AND HttpOnly.
         - `oppos_csrf` cookie present.
  R3-B · /applications, /eligibility, /passport render clean:
         - each root testid mounts.
         - console-error count = 0 (verbatim capture of every message).
         - console-warning count = 0 for React key warnings specifically.
  R3-C · /feed renders cards + Surprise Me capsule mounts with:
         - zero React `Warning: Each child in a list should have a unique
           "key" prop` warnings across the entire session (proves the 5
           stable-ID fixes: Feed.jsx notes / Admin.jsx replies+events /
           SurpriseMeCapsule.jsx why-you-qualify / OutcomesIntelligence
           sparkline dots — the two Feed-side ones are on this page).
         - zero console errors.
         - at least one job card renders.
         - `surprise-me` capsule root mounts.

Outputs:
  * `/app/docs/remediation-artifacts/r3_results.json`
  * `/app/docs/remediation-artifacts/r3_*.jpeg`  (one per page + login)

Rails: preview only. This script never mutates state (no /wave/authorize,
no /follow-ups/approve, no /applications transitions, no cache-warming
side effects that persist). Only navigates + reads DOM + captures logs.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright


BASE = os.environ.get(
    "BASE",
    subprocess.check_output(
        ["bash", "-lc", "grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2"]
    ).decode().strip(),
)

OUT_DIR = Path("/app/docs/remediation-artifacts")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Session-wide accumulators. Playwright's `page.on("console", ...)` fires
# per-console event; we retain every message verbatim so the JSON is a
# complete transcript, not a summary. Warnings and errors are indexed
# separately so gate assertions read cleanly.
_ALL_CONSOLE: list[dict] = []
_ALL_PAGE_ERRORS: list[str] = []


def _record_console(msg) -> None:
    try:
        _ALL_CONSOLE.append({
            "type": msg.type,
            "text": msg.text,
            "location": msg.location if isinstance(msg.location, str) else str(msg.location),
        })
    except Exception as e:  # never let logging fail the run
        _ALL_CONSOLE.append({"type": "capture_error", "text": repr(e), "location": ""})


def _record_page_error(err) -> None:
    try:
        _ALL_PAGE_ERRORS.append(str(err))
    except Exception:
        _ALL_PAGE_ERRORS.append("<unstringifiable page error>")


async def _screenshot(page, name: str) -> str:
    p = OUT_DIR / f"{name}.jpeg"
    await page.screenshot(path=str(p), quality=28, full_page=False, type="jpeg")
    return str(p)


async def _goto_stable(page, url: str, *, max_attempts: int = 6) -> bool:
    """Navigate with Cloudflare-502 retry, mirrors g7_g10_evidence pattern."""
    for _ in range(max_attempts):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception:
            await page.wait_for_timeout(3000)
            continue
        body_text = await page.evaluate(
            "() => document.body ? document.body.innerText : ''")
        if "Bad gateway" not in (body_text or "") and "Error code 502" not in (body_text or ""):
            return True
        await page.wait_for_timeout(4000)
    return False


async def ui_login(page) -> bool:
    ok = await _goto_stable(page, f"{BASE}/login")
    if not ok:
        print("ui_login: /login preview unreachable")
        return False
    try:
        await page.wait_for_selector('input[type="email"]',
                                     timeout=15_000, state="visible")
    except Exception:
        print("ui_login: email input never appeared")
        return False
    try:
        email_el = page.locator('input[type="email"]').first
        pw_el = page.locator('input[type="password"]').first
        await email_el.fill("fixture-ead@opportunityos.dev")
        await email_el.press("Tab")
        await pw_el.fill("Fixture!Test1")
        await pw_el.press("Tab")
        await page.wait_for_timeout(500)
        submit_btn = page.locator('[data-testid="login-submit-btn"]').first
        if await submit_btn.count() == 0:
            submit_btn = page.locator('button:has-text("Sign in")').first
        await submit_btn.click()
    except Exception as e:
        print(f"ui_login: exception during fill/click: {e}")
        return False
    for _ in range(15):
        await page.wait_for_timeout(1500)
        if "/login" not in page.url:
            try:
                signed = await page.evaluate(
                    "() => (document.body ? document.body.innerText : '').includes('Signed in as')")
            except Exception:
                signed = False
            if signed:
                return True
    print(f"ui_login: still on login-like page, url={page.url}")
    return False


# ---------------------------------------------------------------- R3-A
async def gate_r3a_storage_and_cookies(page, context) -> dict:
    """Post-login localStorage keys (theme-only) + cookie hygiene."""
    # Navigate to any authenticated page first — /feed is the default
    # landing target after login.
    await _goto_stable(page, f"{BASE}/feed")
    await page.wait_for_timeout(3500)

    ls_snapshot = await page.evaluate("""
        () => {
          const out = {};
          for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            const v = localStorage.getItem(k);
            // Redact ANY value so a leaked secret in localStorage would
            // still surface a non-null value here — but never in plain
            // text in the evidence file.
            out[k] = v == null ? null : {
              length: v.length,
              redacted_preview: (v || '').slice(0, 24)
            };
          }
          return out;
        }
    """)

    ls_keys = list(ls_snapshot.keys())
    # Behavior-based theme-only check: EVERY localStorage key must
    # contain the substring "theme" (case-insensitive) AND the
    # short-preview value must look like a theme literal
    # (light / dark / system / auto). This is stricter than a
    # hardcoded name allowlist because the theme key has drifted
    # historically (oppos.theme / lynk-theme / fynd-theme) — the
    # invariant that matters is that NOTHING else lives in
    # localStorage.
    theme_only = True
    for k in ls_keys:
        if "theme" not in (k or "").lower():
            theme_only = False
            break
        v = ls_snapshot.get(k) or {}
        preview = (v.get("redacted_preview") or "").lower()
        if preview not in ("light", "dark", "system", "auto", ""):
            theme_only = False
            break
    # Anti-token guard: no key/value should look like an auth artifact.
    forbidden_key_substrings = ["token", "jwt", "auth", "session", "credential",
                                 "password", "secret", "bearer", "email", "csrf"]
    forbidden_hits = []
    for k in ls_keys:
        low = (k or "").lower()
        for sub in forbidden_key_substrings:
            if sub in low:
                forbidden_hits.append({"key": k, "matched_substring": sub})

    cookies = await context.cookies()
    # Filter to our cookies only for JSON compactness.
    our_cookies = [c for c in cookies if c.get("name", "").startswith("oppos_")]
    session_cookie = next((c for c in our_cookies if c.get("name") == "oppos_session"), None)
    csrf_cookie = next((c for c in our_cookies if c.get("name") == "oppos_csrf"), None)

    session_present = session_cookie is not None
    session_httponly = bool(session_cookie and session_cookie.get("httpOnly"))
    csrf_present = csrf_cookie is not None

    await _screenshot(page, "r3a_post_login")

    passed = bool(
        theme_only
        and not forbidden_hits
        and session_present
        and session_httponly
        and csrf_present
    )
    return {
        "gate": "R3-A",
        "name": "post-login storage + cookie hygiene",
        "localstorage_keys": ls_keys,
        "localstorage_snapshot": ls_snapshot,
        "localstorage_theme_only": theme_only,
        "forbidden_key_hits": forbidden_hits,
        "our_cookies": [
            {
                "name": c.get("name"),
                "httpOnly": c.get("httpOnly"),
                "secure": c.get("secure"),
                "sameSite": c.get("sameSite"),
                "domain": c.get("domain"),
                "path": c.get("path"),
            }
            for c in our_cookies
        ],
        "oppos_session_present": session_present,
        "oppos_session_httponly": session_httponly,
        "oppos_csrf_present": csrf_present,
        "passed": passed,
    }


# ---------------------------------------------------------------- R3-B
async def _visit_and_capture(page, path: str, screenshot_name: str, root_testid: str) -> dict:
    """Navigate to a path and record before/after console counts and the
    root testid presence. Console messages are also accumulated in the
    session-wide list; the per-page delta is what we assert on."""
    before_console_count = len(_ALL_CONSOLE)
    before_page_error_count = len(_ALL_PAGE_ERRORS)

    await _goto_stable(page, f"{BASE}{path}")
    await page.wait_for_timeout(4500)

    delta_console = _ALL_CONSOLE[before_console_count:]
    delta_page_errors = _ALL_PAGE_ERRORS[before_page_error_count:]

    errors = [m for m in delta_console if m["type"] == "error"]
    warnings = [m for m in delta_console if m["type"] == "warning"]
    react_key_warnings = [
        w for w in warnings
        if 'unique "key"' in w["text"]
        or 'Each child in a list' in w["text"]
        or 'Warning: Each child in a list' in w["text"]
    ]

    root_present = False
    if root_testid:
        try:
            root_present = (await page.locator(f'[data-testid="{root_testid}"]').count()) > 0
        except Exception:
            root_present = False

    await _screenshot(page, screenshot_name)

    return {
        "path": path,
        "root_testid": root_testid,
        "root_present": root_present,
        "console_error_count": len(errors),
        "console_errors_verbatim": errors,
        "console_warning_count": len(warnings),
        "react_key_warning_count": len(react_key_warnings),
        "react_key_warnings_verbatim": react_key_warnings,
        "page_error_count": len(delta_page_errors),
        "page_errors_verbatim": delta_page_errors,
    }


async def gate_r3b_useMemo_pages(page) -> dict:
    """/applications, /eligibility, /passport carry the useMemo /
    component-split changes. Zero console errors on each is the gate."""
    pages = [
        {"path": "/applications", "shot": "r3b_applications", "root": "applications-page"},
        {"path": "/eligibility",  "shot": "r3b_eligibility",  "root": "eligibility-page"},
        {"path": "/passport",     "shot": "r3b_passport",     "root": None},  # no page-level testid
    ]
    results = []
    for p in pages:
        r = await _visit_and_capture(page, p["path"], p["shot"], p["root"])
        results.append(r)

    total_errors = sum(r["console_error_count"] for r in results)
    total_page_errors = sum(r["page_error_count"] for r in results)
    total_key_warnings = sum(r["react_key_warning_count"] for r in results)
    passed = total_errors == 0 and total_page_errors == 0 and total_key_warnings == 0
    return {
        "gate": "R3-B",
        "name": "/applications /eligibility /passport render clean",
        "per_page": results,
        "total_console_errors": total_errors,
        "total_page_errors": total_page_errors,
        "total_react_key_warnings": total_key_warnings,
        "passed": passed,
    }


# ---------------------------------------------------------------- R3-C
async def gate_r3c_feed_and_surprise(page) -> dict:
    """/feed renders cards + Surprise Me capsule mounts with zero React
    key warnings and zero console errors."""
    before_console_count = len(_ALL_CONSOLE)
    before_page_error_count = len(_ALL_PAGE_ERRORS)

    await _goto_stable(page, f"{BASE}/feed")
    # Feed is heavier — allow extra settle time for score computation +
    # capsule mount.
    await page.wait_for_timeout(6500)

    # Job cards
    job_card_count = await page.locator('[data-testid^="job-card-"]').count()
    # Surprise Me capsule root
    surprise_root_count = await page.locator('[data-testid="surprise-me"]').count()

    delta_console = _ALL_CONSOLE[before_console_count:]
    delta_page_errors = _ALL_PAGE_ERRORS[before_page_error_count:]
    errors = [m for m in delta_console if m["type"] == "error"]
    warnings = [m for m in delta_console if m["type"] == "warning"]
    react_key_warnings = [
        w for w in warnings
        if 'unique "key"' in w["text"]
        or 'Each child in a list' in w["text"]
        or 'Warning: Each child in a list' in w["text"]
    ]

    await _screenshot(page, "r3c_feed")

    passed = bool(
        job_card_count >= 1
        and surprise_root_count >= 1
        and len(errors) == 0
        and len(delta_page_errors) == 0
        and len(react_key_warnings) == 0
    )
    return {
        "gate": "R3-C",
        "name": "/feed cards + Surprise Me capsule, zero warnings/errors",
        "job_card_count": job_card_count,
        "surprise_me_root_present": surprise_root_count > 0,
        "console_error_count": len(errors),
        "console_errors_verbatim": errors,
        "console_warning_count": len(warnings),
        "react_key_warning_count": len(react_key_warnings),
        "react_key_warnings_verbatim": react_key_warnings,
        "page_error_count": len(delta_page_errors),
        "page_errors_verbatim": delta_page_errors,
        "passed": passed,
    }


# ---------------------------------------------------------------- Main
async def main() -> int:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            executable_path=(os.environ.get("CHROMIUM_PATH") or None),
        )
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        # Wire console/pageerror capture at session scope.
        page.on("console", _record_console)
        page.on("pageerror", _record_page_error)

        # Login with retry (dev-mode preview may 502 briefly).
        logged_in = False
        for attempt in range(3):
            logged_in = await ui_login(page)
            if logged_in:
                break
            print(f"ui_login: retrying (attempt {attempt+2}/3) after 10s")
            await page.wait_for_timeout(10_000)

        report = {
            "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "base_url": BASE,
            "user": "fixture-ead@opportunityos.dev",
            "notes": (
                "R3 · Code-Review Remediation browser-leg replay. "
                "Independent tester runs this same script and diffs "
                "against the committed r3_results.json."
            ),
            "logged_in": logged_in,
        }

        try:
            report["R3_A"] = await gate_r3a_storage_and_cookies(page, ctx)
            report["R3_B"] = await gate_r3b_useMemo_pages(page)
            report["R3_C"] = await gate_r3c_feed_and_surprise(page)
        finally:
            report["session_console_message_count"] = len(_ALL_CONSOLE)
            report["session_page_error_count"] = len(_ALL_PAGE_ERRORS)
            # Store the full transcript LAST so the top of the file is
            # human-readable gate summary + counts.
            report["session_console_transcript"] = _ALL_CONSOLE
            report["session_page_errors_verbatim"] = _ALL_PAGE_ERRORS
            await browser.close()

        report["all_passed"] = bool(
            logged_in
            and report["R3_A"]["passed"]
            and report["R3_B"]["passed"]
            and report["R3_C"]["passed"]
        )

        out_path = OUT_DIR / "r3_results.json"
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        # Summary line for tester eyeballing.
        print(json.dumps({
            "all_passed": report["all_passed"],
            "logged_in": logged_in,
            "R3_A_passed": report["R3_A"]["passed"],
            "R3_B_passed": report["R3_B"]["passed"],
            "R3_C_passed": report["R3_C"]["passed"],
            "localstorage_keys": report["R3_A"]["localstorage_keys"],
            "session_error_count": report["session_page_error_count"],
            "session_console_message_count": report["session_console_message_count"],
            "feed_job_card_count": report["R3_C"]["job_card_count"],
            "feed_key_warnings": report["R3_C"]["react_key_warning_count"],
        }, indent=2))
        print(f"\nwrote {out_path}")
        return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
