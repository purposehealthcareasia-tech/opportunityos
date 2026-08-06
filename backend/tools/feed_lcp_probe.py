"""Phase 1 Step (iii) — Feed LCP re-measure.

Post-scorer-unfreeze LCP for /feed as fixture-ead@. Compared honestly
against Phase 0 closeout Playwright LCP of 3.98 s.

Preview runs `react-scripts start` (dev) + uvicorn --reload — dev mode
caps performance ~20-30 pts below a production build. This is a
"is the direction right?" measurement, not a production number.

Run: python3 backend/tools/feed_lcp_probe.py
"""
import asyncio, json, os, statistics, subprocess, sys, time

BASE = os.environ.get("BASE") or subprocess.check_output(
    ["bash","-lc","grep REACT_APP_BACKEND_URL /app/frontend/.env | cut -d= -f2"]).decode().strip()

async def measure_once(pw, idx: int) -> dict:
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport={"width": 1400, "height": 900})
    page = await ctx.new_page()
    # 1) log in via API so we bring cookies into the browser context.
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
    # 2) navigate to /feed and wait for network idle
    t0 = time.time()
    await page.goto(f"{BASE}/feed", wait_until="networkidle", timeout=60_000)
    t1 = time.time()
    # 3) collect LCP via PerformanceObserver
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
    return {
        "idx": idx,
        "wall_time_s": round(t1 - t0, 3),
        "lcp_ms": round(lcp, 1),
        "ttfb_ms": round(nav.get("ttfb") or 0, 1),
        "dom_content_loaded_ms": round(nav.get("domContentLoaded") or 0, 1),
        "load_ms": round(nav.get("load") or 0, 1),
    }

async def main():
    from playwright.async_api import async_playwright
    runs = int(os.environ.get("RUNS", "3"))
    results = []
    async with async_playwright() as pw:
        for i in range(runs):
            r = await measure_once(pw, i + 1)
            print(json.dumps(r))
            results.append(r)
    lcps = [r["lcp_ms"] for r in results if r["lcp_ms"] > 0]
    walls = [r["wall_time_s"] for r in results]
    summary = {
        "runs": runs,
        "base_url": BASE,
        "note": "dev-mode preview (react-scripts start + uvicorn --reload); production build will be faster",
        "wall_time_median_s": statistics.median(walls) if walls else None,
        "wall_time_min_s": min(walls) if walls else None,
        "lcp_median_ms": statistics.median(lcps) if lcps else None,
        "lcp_min_ms": min(lcps) if lcps else None,
        "raw": results,
    }
    print("---SUMMARY---")
    print(json.dumps(summary, indent=2))
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w") as f:
            json.dump(summary, f, indent=2)

if __name__ == "__main__":
    asyncio.run(main())
