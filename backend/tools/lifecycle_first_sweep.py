"""Lifecycle-sweep runner — first-pass tool.

Standalone script. Runs `services.lifecycle_sweep.sweep_all()` against
the full 158-tuple catalog and prints a one-line audit summary suitable
for the founder-report format.

Usage:
    python3 backend/tools/lifecycle_first_sweep.py

The sweep NEVER submits or emails; it only reads adapter feeds and marks
existing DB rows closed when their `external_id` has vanished from the
source board.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> int:
    from services import lifecycle_sweep as sweep
    summary = await sweep.sweep_all(actor="first-sweep-cli")
    # Preserve full per-board detail for the audit collection, but print
    # the founder one-liner + the top-3 boards contributing to the close count.
    per_board = summary["per_board"]
    top_closed = sorted(per_board, key=lambda b: -b["closed"])[:3]
    print(f"lifecycle-sweep · boards_probed={summary['boards_probed']} "
          f"boards_swept={summary['boards_swept']} "
          f"boards_skipped_ambiguous={summary['boards_skipped_ambiguous']} "
          f"boards_errored={summary['boards_errored']} · "
          f"closed_total={summary['closed_total']} "
          f"stamped_last_polled_at={summary['stamped_total']} · "
          f"fresh_ids_total={summary['fresh_ids_total']}")
    print(f"top-3 closed contributors:")
    for b in top_closed:
        print(f"  {b['source_ats']:10s} {b['token']:25s} "
              f"closed={b['closed']:>5}  fresh_now={b['fresh_ids']:>5}")
    print(f"\nfull summary keys: {list(summary.keys())}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
