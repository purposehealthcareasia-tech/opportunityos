"""Route Census — Phase 4 · Item 1 backlog (re-probe portal-other with backoff).

Founder-authorized. Read-only classification of application-route type per
job via plain HTTP GET (no form interaction, no submission, no CAPTCHA
interaction). Persists to `route_census` collection with:

    {
      url, employer, host, ats,
      http_status, http_ok, response_bytes,
      classification (see below),
      first_seen, last_probed,
      retry_count, transient_failures,
    }

Classifications:
    gh-noCap    Greenhouse boards (no CAPTCHA on the apply route)
    lever-cap   Lever postings (typically CAPTCHA-gated)
    ashby       Ashby postings (JS-rendered SPA)
    workday     Workday tenant portals (custom domains cxs./workdayjobs.com)
    portal-other Every other host / non-2xx / network-error case
    dns-error   Host does not resolve
    timeout     Timed out after 15s even after retry

Rails:
    * Only GET. No POST. No JavaScript execution.
    * Polite: max 1 req/sec per host; ≤ 3 retries per URL with exponential
      backoff (2s, 5s, 12s); jitter added.
    * User-Agent identifies us: "OpportunityOS-RouteCensus/1.0
      (contact: support@opportunityos.dev)"
    * Aborts if server returns 429 twice in a row: leaves classification
      as `portal-other` with `transient_failures = 2` for later review.
    * Never persists PII from response body (only length, status,
      classification).
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import httpx

sys.path.insert(0, "/app/backend")

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
import os  # noqa: E402


load_dotenv("/app/backend/.env")

USER_AGENT = "OpportunityOS-RouteCensus/1.0 (contact: support@opportunityos.dev)"


def _classify(host: str, status: Optional[int]) -> str:
    h = (host or "").lower()
    if "greenhouse.io" in h:
        # GH job-boards return 200 with a static HTML form; no CAPTCHA on
        # the initial page. CAPTCHA sometimes fires on final POST — we
        # never test that.
        return "gh-noCap" if status == 200 else "portal-other"
    if "lever.co" in h or "jobs.lever.co" in h:
        # Lever fires a hCaptcha for many customers on the apply POST;
        # the GET is clean.
        return "lever-cap" if status == 200 else "portal-other"
    if "ashbyhq.com" in h:
        return "ashby" if status == 200 else "portal-other"
    if "workdayjobs.com" in h or "myworkdayjobs.com" in h or "wd5.myworkday" in h:
        return "workday" if status == 200 else "portal-other"
    return "portal-other"


async def _probe_one(client: httpx.AsyncClient, url: str, url_row: dict,
                     host_last_hit: dict[str, float],
                     lock: asyncio.Lock) -> dict:
    """Probe one URL with polite pacing + up to 3 retries on 429/5xx/timeout."""
    parsed = urlparse(url)
    host = parsed.netloc
    result = {
        "url": url,
        "employer": url_row.get("employer"),
        "host": host,
        "ats": url_row.get("ats"),
        "http_status": None,
        "http_ok": False,
        "response_bytes": None,
        "classification": "portal-other",
        "first_seen": datetime.now(timezone.utc),
        "last_probed": datetime.now(timezone.utc),
        "retry_count": 0,
        "transient_failures": 0,
    }
    for attempt in range(3):
        # Rate-limit per host: at least 1s between hits.
        async with lock:
            now = time.monotonic()
            wait_needed = 1.0 - (now - host_last_hit.get(host, 0))
            if wait_needed > 0:
                await asyncio.sleep(wait_needed + random.uniform(0.05, 0.35))
            host_last_hit[host] = time.monotonic()

        try:
            r = await client.get(url, follow_redirects=True, timeout=15.0)
            result["http_status"] = r.status_code
            result["http_ok"] = r.is_success
            result["response_bytes"] = len(r.content)
            if r.status_code in (429, 500, 502, 503, 504):
                result["transient_failures"] += 1
                if attempt < 2:
                    result["retry_count"] += 1
                    backoff = (2, 5, 12)[attempt] + random.uniform(0, 1.5)
                    await asyncio.sleep(backoff)
                    continue
            # Non-retryable outcome (2xx/3xx/4xx-other) — classify + return.
            result["classification"] = _classify(host, r.status_code)
            result["last_probed"] = datetime.now(timezone.utc)
            return result
        except httpx.ConnectError:
            result["classification"] = "dns-error"
            result["transient_failures"] += 1
            return result
        except (httpx.TimeoutException, httpx.ReadTimeout):
            result["transient_failures"] += 1
            if attempt < 2:
                result["retry_count"] += 1
                await asyncio.sleep((2, 5, 12)[attempt] + random.uniform(0, 1.5))
                continue
            result["classification"] = "timeout"
            result["last_probed"] = datetime.now(timezone.utc)
            return result
        except Exception:
            result["transient_failures"] += 1
            if attempt < 2:
                result["retry_count"] += 1
                await asyncio.sleep((2, 5, 12)[attempt] + random.uniform(0, 1.5))
                continue
            return result
    # Exhausted retries
    result["classification"] = "portal-other"
    return result


async def _sample_from_db(db, n: int) -> list[dict]:
    """Sample N live discovery URLs, deduped by employer to avoid over-
    representing a single company."""
    pipe = [
        {"$match": {"status": "live",
                     "source": {"$regex": r"^discovery\."},
                     "origin_url": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$company_name",
                     "url": {"$first": "$origin_url"},
                     "ats": {"$first": "$source"}}},
        {"$sample": {"size": n}},
        {"$project": {"_id": 0, "employer": "$_id", "url": 1, "ats": 1}},
    ]
    return [r async for r in db.jobs.aggregate(pipe)]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    client_db = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client_db[os.environ["DB_NAME"]]
    sample = await _sample_from_db(db, args.limit)
    started = datetime.now(timezone.utc)
    print(f"Sampled {len(sample)} distinct-employer URLs; probing...", flush=True)

    host_last_hit: dict[str, float] = defaultdict(float)
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(args.concurrency)

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT,
                 "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"},
        http2=False,
    ) as client:
        async def _bound(url_row):
            async with sem:
                return await _probe_one(client, url_row["url"], url_row,
                                          host_last_hit, lock)
        results = await asyncio.gather(*(_bound(r) for r in sample))

    # Persist and summarize.
    finished = datetime.now(timezone.utc)
    by_class: dict[str, int] = defaultdict(int)
    from pymongo import UpdateOne
    ops = []
    for r in results:
        by_class[r["classification"]] += 1
        set_fields = {k: v for k, v in r.items() if k != "first_seen"}
        ops.append(UpdateOne(
            {"url": r["url"]},
            {"$set": set_fields,
             "$setOnInsert": {"first_seen": r["first_seen"]}},
            upsert=True,
        ))
    if ops:
        await db.route_census.bulk_write(ops, ordered=False)

    summary = {
        "id": f"census-{int(started.timestamp())}",
        "started_at": started, "finished_at": finished,
        "elapsed_s": round((finished - started).total_seconds(), 2),
        "sample_size": len(sample),
        "by_classification": dict(by_class),
        "concurrency": args.concurrency,
    }
    await db.route_census_runs.insert_one({**summary,
                                             "created_at": datetime.now(timezone.utc)})
    print("Route census complete:", flush=True)
    print(f"  Sample size: {summary['sample_size']}")
    print(f"  Elapsed:     {summary['elapsed_s']}s")
    print("  By classification:")
    for k in sorted(by_class, key=lambda x: -by_class[x]):
        print(f"    {k:16s} {by_class[k]}")


if __name__ == "__main__":
    asyncio.run(main())
