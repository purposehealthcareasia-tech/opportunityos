"""Catalog expansion candidate list + verifier — Phase 4 backlog.

Adds only tokens that pass a live probe:
    * Greenhouse: GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs -> 200 + jobs > 0
    * Lever:      GET https://api.lever.co/v0/postings/{token}?mode=json    -> 200 + array > 0
    * Ashby:      GET https://api.ashbyhq.com/posting-api/job-board/{token} -> 200 + jobs > 0

Any candidate that returns non-200 OR zero postings is DROPPED and reported.
Verified tuples are printed to stdout in the same shape as catalog.py; the
main agent can copy them into GREENHOUSE_BOARDS / LEVER_BOARDS / ASHBY_BOARDS
if the founder approves.

Founder rails held: read-only HTTP GET; polite pacing; no writes; nothing
here contacts a job board's HTML apply route or triggers any submission.
"""
from __future__ import annotations

import asyncio
import time

import httpx


USER_AGENT = ("OpportunityOS-CatalogVerify/1.0 "
              "(contact: support@opportunityos.dev)")

# Candidate additions — publicly-documented Greenhouse / Lever / Ashby boards
# for well-known employers not yet in our catalog. These are candidate tokens
# only; we verify each below before recommending inclusion.
GH_CANDIDATES = [
    ("Airbnb", "airbnb"),
    ("Anthropic", "anthropic"),
    ("Stripe", "stripe"),
    ("Notion", "notion"),
    ("Figma", "figma"),
    ("Coinbase", "coinbase"),
    ("Robinhood", "robinhood"),
    ("Palantir", "palantirtechnologies"),
    ("DoorDash", "doordash"),
    ("Instacart", "instacart"),
    ("Rippling", "rippling"),
    ("Ramp", "ramp"),
    ("Brex", "brex"),
    ("Mercury", "mercury"),
    ("Vercel", "vercel"),
    ("Retool", "retool"),
    ("Chime", "chime"),
    ("Gusto", "gusto"),
    ("Dropbox", "dropbox"),
    ("Reddit", "reddit"),
    ("Pinterest", "pinterest"),
    ("Cloudflare", "cloudflareinc"),
    ("Snowflake", "snowflakecomputing"),
    ("HashiCorp", "hashicorp"),
    ("Zapier", "zapier"),
    ("Loom", "loom"),
    ("Discord", "discord"),
    ("Rivian", "rivian"),
    ("Cruise", "cruise"),
    ("Aurora", "aurora"),
    ("Zoox", "zoox"),
    ("Nuro", "nuro"),
    ("Motional", "motional"),
    ("Bolt", "bolt"),
    ("Turo", "turo"),
    ("Convoy", "convoyinc"),
    ("Faire", "faire"),
    ("Discord", "discord"),
]

LEVER_CANDIDATES = [
    ("Netflix", "netflix"),
    ("Palo Alto Networks", "paloaltonetworks"),
    ("Yelp", "yelp"),
    ("KeepTruckin", "keeptruckin"),
    ("Cerebras", "cerebras"),
    ("Attentive", "attentive"),
    ("Grammarly", "grammarly"),
    ("SentinelOne", "sentinelone"),
    ("Wealthfront", "wealthfront"),
    ("Rocket Money", "rocketmoney"),
]

ASHBY_CANDIDATES = [
    ("Perplexity", "perplexity"),
    ("Cursor", "cursor"),
    ("Anysphere", "anysphere"),
    ("Together AI", "togetherai"),
    ("Cohere", "cohere"),
    ("Runway", "runwayml"),
    ("Character AI", "characterai"),
    ("Mistral AI", "mistral"),
    ("Groq", "groq"),
    ("Modal", "modal"),
    ("Poolside", "poolsideai"),
    ("Sierra", "sierra"),
    ("Genesis Therapeutics", "genesistherapeutics"),
    ("Braintrust", "braintrust"),
    ("Vellum", "vellumai"),
]


async def _verify_gh(client: httpx.AsyncClient, token: str) -> tuple[int, int]:
    r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
                          timeout=15.0)
    if r.status_code != 200:
        return r.status_code, 0
    try:
        n = len((r.json() or {}).get("jobs") or [])
    except Exception:
        n = 0
    return 200, n


async def _verify_lever(client: httpx.AsyncClient, token: str) -> tuple[int, int]:
    r = await client.get(f"https://api.lever.co/v0/postings/{token}?mode=json",
                          timeout=15.0)
    if r.status_code != 200:
        return r.status_code, 0
    try:
        n = len(r.json() or [])
    except Exception:
        n = 0
    return 200, n


async def _verify_ashby(client: httpx.AsyncClient, token: str) -> tuple[int, int]:
    r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}",
                          timeout=15.0)
    if r.status_code != 200:
        return r.status_code, 0
    try:
        n = len((r.json() or {}).get("jobs") or [])
    except Exception:
        n = 0
    return 200, n


async def main() -> None:
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        kept_gh, kept_lever, kept_ashby = [], [], []
        dropped: list[tuple[str, str, str, int, int]] = []
        for name, token in GH_CANDIDATES:
            try:
                status, n = await _verify_gh(client, token)
            except Exception as e:
                status, n = 0, 0
            if status == 200 and n > 0:
                kept_gh.append((name, token, n))
            else:
                dropped.append(("greenhouse", name, token, status, n))
            await asyncio.sleep(0.5)
        for name, token in LEVER_CANDIDATES:
            try:
                status, n = await _verify_lever(client, token)
            except Exception:
                status, n = 0, 0
            if status == 200 and n > 0:
                kept_lever.append((name, token, n))
            else:
                dropped.append(("lever", name, token, status, n))
            await asyncio.sleep(0.5)
        for name, token in ASHBY_CANDIDATES:
            try:
                status, n = await _verify_ashby(client, token)
            except Exception:
                status, n = 0, 0
            if status == 200 and n > 0:
                kept_ashby.append((name, token, n))
            else:
                dropped.append(("ashby", name, token, status, n))
            await asyncio.sleep(0.5)

    print(f"=== VERIFIED KEEPS ({len(kept_gh) + len(kept_lever) + len(kept_ashby)}) ===")
    print("# Add to GREENHOUSE_BOARDS:")
    for name, token, n in sorted(kept_gh):
        print(f'    ("{name}", "{token}"),  # {n} jobs')
    print("# Add to LEVER_BOARDS:")
    for name, token, n in sorted(kept_lever):
        print(f'    ("{name}", "{token}"),  # {n} jobs')
    print("# Add to ASHBY_BOARDS:")
    for name, token, n in sorted(kept_ashby):
        print(f'    ("{name}", "{token}"),  # {n} jobs')
    print(f"\n=== DROPPED ({len(dropped)}) ===")
    for ats, name, token, status, n in dropped:
        print(f'  {ats} "{name}" token={token} status={status} n={n}')


if __name__ == "__main__":
    asyncio.run(main())
