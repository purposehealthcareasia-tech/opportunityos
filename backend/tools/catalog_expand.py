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
# for well-known engineering employers not yet in our catalog. These are
# CANDIDATE tokens only; each is probed live below and DROPPED honestly if
# the endpoint returns non-200 or zero postings. No token is added on a
# guess — verification is the only path.
#
# NOT IN CATALOG YET (2026-07-28 audit before this pass ran):
#   GH_BOARDS = 75, LEVER_BOARDS = 3, ASHBY_BOARDS = 44 → 122 total.
GH_CANDIDATES = [
    # Round 3 (2026-07-28) — final push to 150+. Focused on companies I have
    # strong prior evidence for their board existence (public URLs seen).
    ("Alethea", "alethea"),
    ("Anrok Careers", "anrok"),         # main list has anrok on ashby
    ("Character.AI", "characterai"),
    ("Cohere Careers", "cohere"),        # main list has cohere on ashby
    ("Cresta", "cresta"),
    ("Descript", "descript"),
    ("Docker", "docker"),
    ("Envoy", "envoy"),
    ("Etsy", "etsy"),
    ("Formic", "formicrobots"),
    ("Foundation", "foundation"),
    ("Ghost Autonomy", "ghostlocomotion"),
    ("Hex", "hex"),
    ("Intercom", "intercom"),
    ("Ironclad", "ironclad"),
    ("Jasper", "jasper"),
    ("Loft Orbital", "loftorbital"),      # already in Lever main list; check GH form
    ("Mux", "mux"),
    ("Netlify", "netlify"),
    ("Notion", "notion"),                  # main list has notion on ashby — verify GH form
    ("Persona", "persona"),
    ("Reforge", "reforge"),
    ("Robocorp", "robocorp"),
    ("Rockwell Automation", "rockwellautomation"),
    ("Rubrik", "rubrik"),
    ("Segment", "segment"),
    ("Slite", "slite"),
    ("Snyk", "snyk"),
    ("Sonder", "sonder"),
    ("Tessera Therapeutics", "tesseratx"),
    ("Tulip", "tulip"),
    ("Unity", "unity3d"),
    ("Vimeo", "vimeo"),
    ("Whimsical", "whimsical"),
    ("YouGov", "yougov"),
]

LEVER_CANDIDATES = [
    ("Alan", "alan"),
    ("Boulevard", "boulevard"),
    ("Deel", "deel"),
    ("Everbridge", "everbridge"),
    ("Postman", "postman"),
    ("Sisu", "sisu"),
    ("Slack", "slack"),
    ("Snyk", "snyk"),
    ("Stord", "stord"),
    ("Vercel Careers", "vercel"),
    ("Vimeo", "vimeo"),
    ("Whatnot", "whatnot"),
    ("Zapier Careers", "zapier"),
]

ASHBY_CANDIDATES = [
    ("Adept AI", "adeptai"),
    ("Airplane", "airplane"),
    ("Anthropic Public", "anthropic"),   # main list has anthropic on greenhouse
    ("Beam", "beam"),
    ("Buildkite", "buildkite"),
    ("Character AI Full", "character-ai"),
    ("Chroma AI", "trychroma"),
    ("Delve AI", "delve"),
    ("Dust", "dust-tt"),
    ("Elicit", "elicit"),
    ("Featureform", "featureform"),
    ("Fixie", "fixie"),
    ("Fivetran", "fivetran"),
    ("Highlight", "highlight"),
    ("Kestra", "kestra"),
    ("Modal Labs", "modal-labs"),        # main list has "modal"
    ("Motion", "motion"),
    ("Neon Serverless", "neon"),          # main list has neon
    ("Notion Labs Full", "notionhq"),
    ("Osmos", "osmos"),
    ("Parabola", "parabola"),
    ("Rocket Money", "rocketmoney"),
    ("Runpod", "runpod"),
    ("Statsig", "statsig"),
    ("Together", "together"),
    ("Union", "unionai"),
    ("Waymark", "waymark"),
    ("WorkOS", "workos"),
    ("XBOW", "xbow"),
    ("Zed Full", "zed-industries"),      # main list has zed
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
