"""Apply-at-birth tier classification report — read-only.

Reports the velocity tier of every catalog board plus the median
posting→queue lag over the last 24 h. Does NOT hit employer origins;
purely reads from the local `jobs` collection.

Usage:
    python3 backend/tools/apply_at_birth_report.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> int:
    from services import apply_at_birth as aab
    from datetime import datetime, timezone
    from domains.discovery.catalog import ALL_BOARDS

    now = datetime.now(timezone.utc)
    tiers = Counter()
    per_tier_examples = {aab.TIER_HOT: [], aab.TIER_WARM: [], aab.TIER_COLD: []}
    for source_ats, employer, token in ALL_BOARDS:
        tier, n_24h, n_7d = await aab._classify_tier(source_ats, token, now)
        tiers[tier] += 1
        if len(per_tier_examples[tier]) < 3:
            per_tier_examples[tier].append(
                f"{employer[:20]:20s} ({source_ats}, {n_24h}/24h, {n_7d}/7d)")

    median_lag = await aab._median_lag_minutes(now)
    print(f"apply-at-birth · tiers {aab.TIER_HOT}={tiers[aab.TIER_HOT]} "
          f"{aab.TIER_WARM}={tiers[aab.TIER_WARM]} "
          f"{aab.TIER_COLD}={tiers[aab.TIER_COLD]} · "
          f"median_posting_to_queue_minutes_last_24h="
          f"{median_lag if median_lag is not None else 'n/a'}")
    for tier in (aab.TIER_HOT, aab.TIER_WARM, aab.TIER_COLD):
        for e in per_tier_examples[tier]:
            print(f"  {tier:5s} · {e}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
