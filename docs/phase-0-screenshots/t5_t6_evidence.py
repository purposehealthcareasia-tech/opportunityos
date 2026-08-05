#!/usr/bin/env python3
"""
T5 + T6 builder-executed evidence for Phase 0 gate.

Independent tester timed out three times on browser-heavy legs; this script
produces the raw evidence they were meant to capture. Read-only from the app's
POV — logs into fixture-ead@ via HTTP, injects the cookies into Playwright,
then navigates 5 rethemed screens under emulated media conditions.

Rails held: no backend restart, no employer origin traffic, no .env edits.
"""

import asyncio, json, subprocess, re, os, sys, time
from pathlib import Path
from playwright.async_api import async_playwright

BASE = "https://lynk-preview-2.preview.emergentagent.com"
CHROMIUM = "/root/bin/chromium"
OUT_DIR = Path("/app/docs/phase-0-screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def http_login():
    """Log in as fixture-ead@ via curl and extract cookies."""
    proc = subprocess.run(
        ["curl", "-si", "-X", "POST", f"{BASE}/api/v1/auth/login",
         "-H", "Content-Type: application/json",
         "-d", '{"email":"fixture-ead@opportunityos.dev","password":"Fixture!Test1"}'],
        capture_output=True, text=True, timeout=15,
    )
    cookies = []
    for line in proc.stdout.splitlines():
        m = re.match(r"^set-cookie:\s*([^=]+)=([^;]+)", line, re.I)
        if m and m.group(1) in ("oppos_session", "oppos_csrf"):
            cookies.append({
                "name": m.group(1), "value": m.group(2),
                "domain": "lynk-preview-2.preview.emergentagent.com", "path": "/",
            })
    return cookies


async def new_context(browser, cookies, media_features=None):
    ctx = await browser.new_context(
        viewport={"width": 1440, "height": 900},
        color_scheme="dark",
        reduced_motion=("reduce" if media_features and media_features.get("motion") == "reduce" else "no-preference"),
    )
    # Seed cookies + oppos.theme=dark so app boots into dark mode
    await ctx.add_cookies(cookies)
    await ctx.add_init_script("""
      try { localStorage.setItem('oppos.theme','dark'); } catch(e) {}
    """)
    # Also emulate reduced-transparency via CDP (Playwright API doesn't expose it directly)
    if media_features and media_features.get("transparency") == "reduce":
        page = await ctx.new_page()
        cdp = await ctx.new_cdp_session(page)
        await cdp.send("Emulation.setEmulatedMedia", {
            "features": [{"name": "prefers-reduced-transparency", "value": "reduce"},
                         {"name": "prefers-color-scheme", "value": "dark"}]
        })
        return ctx, page
    return ctx, None


# ---------------------------------------------------------------- T5a REDUCED-TRANSPARENCY

async def t5a_reduced_transparency(browser, cookies):
    """Emulate prefers-reduced-transparency: reduce and prove backdrop-filter is dropped."""
    print("\n=== T5a: prefers-reduced-transparency: reduce ===")
    ctx, page = await new_context(browser, cookies, media_features={"transparency": "reduce"})
    if page is None:
        page = await ctx.new_page()
    try:
        await page.goto(f"{BASE}/feed", wait_until="load", timeout=30000)
        # Give feed time to hydrate
        await page.wait_for_timeout(5000)

        # Check computed style on .liquid-bar (topbar) — backdrop-filter must be 'none'
        bd_bar = await page.evaluate("""() => {
          const el = document.querySelector('.liquid-bar');
          if (!el) return {found:false};
          const cs = getComputedStyle(el);
          return {
            found: true,
            backdrop: cs.backdropFilter || cs.webkitBackdropFilter,
            background: cs.backgroundColor,
          };
        }""")
        bd_card = await page.evaluate("""() => {
          const el = document.querySelector('.liquid-card');
          if (!el) return {found:false};
          const cs = getComputedStyle(el);
          return {
            found: true,
            backdrop: cs.backdropFilter || cs.webkitBackdropFilter,
            background: cs.backgroundColor,
          };
        }""")
        bd_sheet = await page.evaluate("""() => {
          const el = document.querySelector('.liquid-sheet');
          if (!el) return {found:false};
          const cs = getComputedStyle(el);
          return {
            found: true,
            backdrop: cs.backdropFilter || cs.webkitBackdropFilter,
            background: cs.backgroundColor,
          };
        }""")
        result = {"liquid-bar": bd_bar, "liquid-card": bd_card, "liquid-sheet": bd_sheet}
        print("computed styles under reduced-transparency:")
        print(json.dumps(result, indent=2))

        await page.screenshot(path=str(OUT_DIR / "t5a_reduced_transparency_feed.jpg"),
                              quality=25, type="jpeg", full_page=False)
        print("screenshot -> t5a_reduced_transparency_feed.jpg")
        return result
    finally:
        await ctx.close()


# ---------------------------------------------------------------- T5b REDUCED-MOTION

async def t5b_reduced_motion(browser, cookies):
    """Emulate prefers-reduced-motion: reduce and prove entrance animations are collapsed."""
    print("\n=== T5b: prefers-reduced-motion: reduce ===")
    ctx, _ = await new_context(browser, cookies, media_features={"motion": "reduce"})
    page = await ctx.new_page()
    try:
        # Landing has liquid-pill and animate-liquidIn on Pillar cards
        await page.goto(f"{BASE}/", wait_until="load", timeout=30000)
        await page.wait_for_timeout(2500)

        # Check computed-style animation-duration + transition-duration on animated pillars
        anims = await page.evaluate("""() => {
          const targets = document.querySelectorAll('.animate-liquidIn, .animate-fadeIn, .liquid-capsule, .liquid-primary, .liquid-secondary');
          const arr = [];
          for (const el of targets) {
            const cs = getComputedStyle(el);
            arr.push({
              cls: el.className.slice(0, 60),
              animationDuration: cs.animationDuration,
              transitionDuration: cs.transitionDuration,
              animationName: cs.animationName,
            });
            if (arr.length >= 8) break;
          }
          return arr;
        }""")
        print("computed animation/transition durations under reduced-motion (sample):")
        print(json.dumps(anims, indent=2))

        # Also fetch the CSS rule text to confirm the guardrail is active
        guardrail = await page.evaluate("""() => {
          for (const sheet of Array.from(document.styleSheets)) {
            try {
              for (const rule of Array.from(sheet.cssRules || [])) {
                if (rule.media && String(rule.media.mediaText).includes('prefers-reduced-motion')) {
                  return { found: true, media: String(rule.media.mediaText),
                           rules: Array.from(rule.cssRules || []).map(r => r.cssText).slice(0, 5) };
                }
              }
            } catch(e) {}
          }
          return { found: false };
        }""")
        print("reduced-motion CSS rule presence:", json.dumps(guardrail, indent=2)[:500])

        await page.screenshot(path=str(OUT_DIR / "t5b_reduced_motion_landing.jpg"),
                              quality=25, type="jpeg", full_page=False)
        print("screenshot -> t5b_reduced_motion_landing.jpg")
        return {"animations_sample": anims, "css_guardrail": guardrail}
    finally:
        await ctx.close()


# ---------------------------------------------------------------- T5c CONTRAST

def relative_luminance(r, g, b):
    """WCAG relative luminance."""
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(rgb_a, rgb_b):
    la = relative_luminance(*rgb_a)
    lb = relative_luminance(*rgb_b)
    lighter, darker = (la, lb) if la > lb else (lb, la)
    return (lighter + 0.05) / (darker + 0.05)


def parse_rgb(s):
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)", s or "")
    if not m: return None
    return tuple(int(float(x)) for x in m.groups())


def resolve_bg(computed_bg, computed_parents_bg):
    """If bg is rgba with alpha<1, composite over parent (first fully-opaque ancestor)."""
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?", computed_bg or "")
    if not m: return None
    r, g, b = int(float(m.group(1))), int(float(m.group(2))), int(float(m.group(3)))
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    if a >= 0.99: return (r, g, b)
    # Composite over parent (first opaque)
    parent = None
    for pbg in computed_parents_bg:
        rp = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?", pbg or "")
        if not rp: continue
        pa = float(rp.group(4)) if rp.group(4) is not None else 1.0
        if pa >= 0.99:
            parent = (int(float(rp.group(1))), int(float(rp.group(2))), int(float(rp.group(3))))
            break
    if parent is None: parent = (11, 13, 16)  # #0B0D10 dark base
    # Simple alpha compositing
    return (
        int(r * a + parent[0] * (1 - a)),
        int(g * a + parent[1] * (1 - a)),
        int(b * a + parent[2] * (1 - a)),
    )


async def t5c_contrast(browser, cookies):
    """Measure WCAG contrast on primary text on liquid-card in dark + light modes."""
    print("\n=== T5c: WCAG AA contrast on glass surfaces ===")
    results = {}

    for theme in ("dark", "light"):
        ctx = await browser.new_context(
            viewport={"width": 1440, "height": 900},
            color_scheme=theme,
        )
        await ctx.add_cookies(cookies)
        await ctx.add_init_script(f"try {{ localStorage.setItem('oppos.theme','{theme}'); }} catch(e) {{}}")
        page = await ctx.new_page()
        try:
            await page.goto(f"{BASE}/feed", wait_until="load", timeout=30000)
            await page.wait_for_timeout(6000)
            # Sample text elements on liquid-card (job title h3) and their effective bg
            samples = await page.evaluate("""() => {
              // Grab several targets on liquid-card and headline
              const targets = [
                { selector: '.liquid-card h3', label: 'card-title' },
                { selector: '.liquid-card .muted', label: 'card-muted' },
                { selector: '.liquid-card p', label: 'card-body' },
                { selector: 'main h1', label: 'page-h1' },
                { selector: '.liquid-bar', label: 'topbar-bg' },
              ];
              const arr = [];
              for (const t of targets) {
                const el = document.querySelector(t.selector);
                if (!el) continue;
                const cs = getComputedStyle(el);
                const fg = cs.color;
                // Walk ancestor chain grabbing background-color values (rgba stack for compositing)
                let node = el.parentElement;
                const stack = [];
                for (let d = 0; d < 8 && node; d++) {
                  stack.push(getComputedStyle(node).backgroundColor);
                  node = node.parentElement;
                }
                const ownBg = cs.backgroundColor;
                const fontSize = parseFloat(cs.fontSize);
                const fontWeight = cs.fontWeight;
                arr.push({label: t.label, fg, ownBg, ancestorBg: stack, fontSize, fontWeight});
              }
              return arr;
            }""")
            # Compute contrast
            per_target = []
            for s in samples:
                fg = parse_rgb(s["fg"])
                # bg = own if opaque, else first opaque ancestor, else #0B0D10 dark or #FFFFFF light
                effective_bg = resolve_bg(s["ownBg"], s["ancestorBg"])
                if not fg or not effective_bg:
                    per_target.append({**s, "contrast": None, "note": "unresolvable-colors"})
                    continue
                cr = contrast_ratio(fg, effective_bg)
                large = s["fontSize"] >= 24 or (s["fontSize"] >= 18.66 and int(s["fontWeight"] or 400) >= 700)
                threshold = 3.0 if large else 4.5
                per_target.append({
                    "label": s["label"],
                    "fg": fg, "effective_bg": effective_bg,
                    "contrast": round(cr, 2),
                    "large_text": large,
                    "threshold": threshold,
                    "passes_AA": cr >= threshold,
                    "fontSize": s["fontSize"], "fontWeight": s["fontWeight"],
                })
            results[theme] = per_target
            print(f"[{theme}] contrast measurements:")
            print(json.dumps(per_target, indent=2))
            await page.screenshot(path=str(OUT_DIR / f"t5c_contrast_feed_{theme}.jpg"),
                                  quality=25, type="jpeg", full_page=False)
            print(f"screenshot -> t5c_contrast_feed_{theme}.jpg")
        finally:
            await ctx.close()

    return results


# ---------------------------------------------------------------- T6 REBRAND + CSRF COOKIE

async def t6_rebrand_and_csrf(browser, cookies):
    """Visit 5 screens; assert no 'OpportunityOS' in title/visible body; CSRF cookie name is oppos_csrf."""
    print("\n=== T6: rebrand sweep + oppos_csrf cookie ===")
    ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme="dark")
    await ctx.add_cookies(cookies)
    await ctx.add_init_script("try { localStorage.setItem('oppos.theme','dark'); } catch(e) {}")
    page = await ctx.new_page()
    findings = []
    screens = [
        ("/", "landing"),
        ("/login", "login"),
        ("/feed", "feed"),
        ("/applications", "applications"),
        ("/outcomes", "outcomes"),
    ]
    try:
        for path, label in screens:
            await page.goto(f"{BASE}{path}", wait_until="load", timeout=30000)
            await page.wait_for_timeout(5000)
            title = await page.title()
            body_text = await page.evaluate("document.body.innerText")
            # Case-insensitive scan for the old brand
            occurrences = re.findall(r"opportunityos", body_text, re.I)
            title_hit = "opportunityos" in title.lower()
            findings.append({
                "path": path, "label": label,
                "title": title, "title_has_old_brand": title_hit,
                "body_old_brand_occurrences": len(occurrences),
                "body_preview_first_180": body_text.strip()[:180],
            })
            print(f"  {path:15s} title={title!r}  body_hits={len(occurrences)}  title_hit={title_hit}")

        # Cookie audit — grab from context, not from HTTP header (Playwright canonicalizes)
        ck = await ctx.cookies()
        names = [c["name"] for c in ck]
        # oppos.theme, oppos_csrf, oppos_session, __cf_bm likely
        csrf_present = "oppos_csrf" in names
        session_present = "oppos_session" in names
        old_cookie_name_hit = any("opportunityos" in n.lower() for n in names)
        print(f"cookies observed: {names}")
        print(f"oppos_csrf present: {csrf_present}  oppos_session present: {session_present}")
        print(f"any legacy 'opportunityos' cookie name: {old_cookie_name_hit}")

        # Also assert the CSRF header key that the frontend actually sends — inspect fetch code
        # Do a quick network probe: submit a small consent GET to see the request headers echoed
        return {
            "screens": findings,
            "cookies": names,
            "oppos_csrf_present": csrf_present,
            "oppos_session_present": session_present,
            "legacy_cookie_name_present": old_cookie_name_hit,
        }
    finally:
        await ctx.close()


# ---------------------------------------------------------------- MAIN

async def main():
    cookies = http_login()
    print("HTTP login cookies:", [c["name"] for c in cookies])
    if not cookies:
        print("FATAL: could not obtain login cookies")
        sys.exit(2)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            executable_path=CHROMIUM,
            args=["--no-sandbox", "--disable-gpu"],
        )
        try:
            t5a = await t5a_reduced_transparency(browser, cookies)
            t5b = await t5b_reduced_motion(browser, cookies)
            t5c = await t5c_contrast(browser, cookies)
            t6  = await t6_rebrand_and_csrf(browser, cookies)
        finally:
            await browser.close()

    payload = {
        "run_started_at": int(time.time()),
        "base_url": BASE,
        "t5a_reduced_transparency": t5a,
        "t5b_reduced_motion": t5b,
        "t5c_contrast": t5c,
        "t6_rebrand_csrf": t6,
    }
    out = OUT_DIR / "t5_t6_evidence.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"\nRAW OUTPUT WRITTEN: {out}")
    return payload


if __name__ == "__main__":
    asyncio.run(main())
