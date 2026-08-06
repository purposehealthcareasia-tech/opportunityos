"""Phase 1 §iii — Production-build LCP measurement.

Boots the built CRA bundle on http://127.0.0.1:4173 (already served by
`npx serve -s build -l 4173`) and measures LCP on /feed while logged in
against the preview backend (REACT_APP_BACKEND_URL). Cookies from the
preview API domain must be injected into the Playwright context so the
prod-build frontend's XHR calls to the preview API are authenticated.
"""
import asyncio, json, os, statistics, subprocess, sys, time

STATIC_URL = os.environ.get("STATIC_URL", "http://127.0.0.1:4173")
BASE = os.environ.get("BASE") or subprocess.check_output(
    ["bash","-lc","grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2"]).decode().strip()

async def measure_once(pw, idx: int, url: str) -> dict:
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
    page = await ctx.new_page()
    # Login via preview backend to receive cookies for that origin
    resp = await ctx.request.post(
        f"{BASE}/api/v1/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({
            "email": "fixture-ead@opportunityos.dev",
            "password": "Fixture!Test1"}),
    )
    if resp.status != 200:
        await browser.close()
        raise RuntimeError(f"login {resp.status}")
    # Navigate directly to the target page
    t0 = time.time()
    await page.goto(url, wait_until="networkidle", timeout=60_000)
    t1 = time.time()
    lcp = await page.evaluate(
        """() => new Promise(res => {
            let lcp = 0;
            new PerformanceObserver(list => {
              for (const e of list.getEntries()) lcp = e.startTime;
            }).observe({type:'largest-contentful-paint', buffered:true});
            setTimeout(() => res(lcp), 1500);
        })"""
    )
    nav = await page.evaluate(
        "() => performance.getEntriesByType('navigation').map(e => ({domContentLoaded:e.domContentLoadedEventEnd, load:e.loadEventEnd, ttfb:e.responseStart}))[0]"
    )
    await browser.close()
    return {"idx": idx, "url": url,
             "wall_time_s": round(t1 - t0, 3),
             "lcp_ms": round(lcp, 1),
             "ttfb_ms": round((nav or {}).get("ttfb") or 0, 1),
             "dom_content_loaded_ms": round((nav or {}).get("domContentLoaded") or 0, 1),
             "load_ms": round((nav or {}).get("load") or 0, 1)}

async def main():
    from playwright.async_api import async_playwright
    runs = int(os.environ.get("RUNS", "3"))
    url = os.environ.get("TARGET", f"{STATIC_URL}/feed")
    results = []
    async with async_playwright() as pw:
        for i in range(runs):
            r = await measure_once(pw, i + 1, url)
            print(json.dumps(r))
            results.append(r)
    lcps = [r["lcp_ms"] for r in results if r["lcp_ms"] > 0]
    walls = [r["wall_time_s"] for r in results]
    summary = {
        "runs": runs, "target": url, "backend": BASE,
        "wall_time_median_s": statistics.median(walls) if walls else None,
        "lcp_median_ms": statistics.median(lcps) if lcps else None,
        "lcp_min_ms": min(lcps) if lcps else None,
        "lcp_max_ms": max(lcps) if lcps else None,
        "raw": results,
    }
    print("---SUMMARY---")
    print(json.dumps(summary, indent=2))
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as f: json.dump(summary, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
