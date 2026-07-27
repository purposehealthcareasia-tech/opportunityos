"""Lifecycle sweep — Phase 5.1 truthfulness fix (Founder Directive 2026-07-28).

RULE:
  From now on, `status="live"` on a discovery job means "present on the
  source board as of the last successful poll." When a job's `external_id`
  disappears from its source board feed, mark it `status="closed"` with
  `closed_detected_at`, exclude from live feed counts, and keep the doc
  for receipts / history.

This module implements delta-detection on top of the adapters that
already ingest fresh postings. It NEVER writes new docs — the ingest
path is unchanged. It only transitions live rows to closed when the
source has removed them, and stamps `last_polled_at` on every live row
belonging to a (source_ats, employer_token) we just polled.

Safety rules built in:
  * If an adapter returns an EMPTY list, we do NOT sweep — an empty
    response could indicate a transient fetch failure that the adapter
    swallowed. Only sweep when we have a non-empty fresh set AND the
    fetch completed without raising.
  * A per-board fetch that raises is recorded in `errors` and skipped —
    no rows are transitioned to closed for that board.
  * We NEVER delete. Closed jobs are kept indefinitely so previously-
    stored `submission_receipts.job_id` references remain resolvable.

Public API:
  * sweep_all()             → runs against the full catalog.
  * sweep_one(source, token, employer_name) → runs against one board.

Both return a summary dict shaped for the audit collection.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable

from core import db as core_db
from domains.discovery.catalog import ALL_BOARDS
from domains.discovery.adapters import public_apis as ats


log = logging.getLogger("lifecycle_sweep")

# Reason vocabulary — stable IDs, do not rename.
CLOSED_REASON_ABSENT = "absent_from_source_feed"

# Sweep-tier state — the closed doc keeps enough context that a later
# audit can attribute the transition.
_CLOSED_FIELDS = ("status", "closed_detected_at", "closed_reason",
                    "closed_from_status", "last_polled_at")


async def _fetch_fresh_ids(source_ats: str, employer_name: str, token: str
                             ) -> tuple[set[str], str | None]:
    """Return (fresh_external_id_set, error_message_or_None).

    The set is non-empty on success; None on empty; the error string
    is populated when the adapter raised OR returned zero rows (which we
    treat as ambiguous — do NOT sweep on ambiguity)."""
    try:
        if source_ats == "greenhouse":
            rows = await ats.fetch_greenhouse(employer_name, token)
        elif source_ats == "lever":
            rows = await ats.fetch_lever(employer_name, token)
        elif source_ats == "ashby":
            rows = await ats.fetch_ashby(employer_name, token)
        else:
            return set(), f"unknown_source:{source_ats}"
    except Exception as e:
        return set(), f"fetch_exception:{type(e).__name__}:{str(e)[:120]}"
    if not rows:
        # Ambiguous — could be legit empty board OR transient failure.
        # Do not sweep. Adapter callers can decide separately whether a
        # persistently-empty board should be dropped from the catalog.
        return set(), "empty_response"
    fresh = {str(r.get("external_id") or "") for r in rows}
    fresh.discard("")
    if not fresh:
        return set(), "empty_response_ids"
    return fresh, None


async def sweep_one(source_ats: str, employer_name: str, token: str,
                     *, now: datetime | None = None) -> dict:
    """Sweep a single board. Marks stale rows closed and stamps
    `last_polled_at` on the rest. Returns a per-board summary."""
    now = now or datetime.now(timezone.utc)
    db = core_db.get_db()
    fresh, err = await _fetch_fresh_ids(source_ats, employer_name, token)
    board_summary = {
        "source_ats": source_ats,
        "employer": employer_name,
        "token": token,
        "fresh_ids": len(fresh),
        "closed": 0,
        "stamped_last_polled_at": 0,
        "error": err,
        "polled_at": now.isoformat(),
    }
    if err:
        return board_summary

    # Query all matching live rows.
    query = {
        "status": "live",
        "discovery.source_ats": source_ats,
        "discovery.employer_token": token,
    }
    live_rows = [r async for r in db.jobs.find(
        query, {"_id": 0, "id": 1, "discovery.external_id": 1})]

    # Split into keep vs. close.
    to_close: list[str] = []
    to_stamp: list[str] = []
    for r in live_rows:
        ext_id = str((r.get("discovery") or {}).get("external_id") or "")
        if ext_id and ext_id in fresh:
            to_stamp.append(r["id"])
        else:
            to_close.append(r["id"])

    # Transition closed. update_many is atomic per doc but not across the
    # set — that's fine, order doesn't matter here.
    if to_close:
        res = await db.jobs.update_many(
            {"id": {"$in": to_close}, "status": "live"},
            {"$set": {
                "status": "closed",
                "closed_detected_at": now,
                "closed_reason": CLOSED_REASON_ABSENT,
                "closed_from_status": "live",
                "last_polled_at": now,
            }},
        )
        board_summary["closed"] = res.modified_count
    if to_stamp:
        res = await db.jobs.update_many(
            {"id": {"$in": to_stamp}, "status": "live"},
            {"$set": {"last_polled_at": now}},
        )
        board_summary["stamped_last_polled_at"] = res.modified_count

    return board_summary


async def sweep_all(*, actor: str = "lifecycle-sweep",
                      concurrency: int = 4,
                      boards: Iterable[tuple[str, str, str]] | None = None,
                      ) -> dict:
    """Sweep every board in the catalog (unless `boards` is supplied,
    in which case sweep exactly those). Returns an aggregate summary.

    `boards` is a list of `(source_ats, employer_name, token)`.
    Concurrency is BOARD-level, not host-level; adapters already use one
    HTTP client per board so no per-host lock is needed here. (The
    upstream `discovery.service.refresh_all` uses the same pattern.)"""
    now = datetime.now(timezone.utc)
    boards = list(boards) if boards is not None else list(ALL_BOARDS)
    sem = asyncio.Semaphore(concurrency)

    async def _bound(board):
        async with sem:
            source_ats, employer, token = board
            try:
                return await sweep_one(source_ats, employer, token, now=now)
            except Exception as e:
                return {"source_ats": source_ats, "employer": employer,
                        "token": token, "fresh_ids": 0, "closed": 0,
                        "stamped_last_polled_at": 0,
                        "error": f"unexpected:{type(e).__name__}",
                        "polled_at": now.isoformat()}

    per_board = await asyncio.gather(*[_bound(b) for b in boards])
    summary = {
        "id": f"lifecycle-sweep-{int(now.timestamp())}",
        "started_at": now.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "actor": actor,
        "boards_probed": len(per_board),
        "boards_swept": sum(1 for b in per_board if not b["error"]),
        "boards_skipped_ambiguous": sum(1 for b in per_board
                                          if b["error"] in ("empty_response",
                                                              "empty_response_ids")),
        "boards_errored": sum(1 for b in per_board
                                if b["error"] and
                                b["error"] not in ("empty_response",
                                                     "empty_response_ids")),
        "closed_total": sum(b["closed"] for b in per_board),
        "stamped_total": sum(b["stamped_last_polled_at"] for b in per_board),
        "fresh_ids_total": sum(b["fresh_ids"] for b in per_board),
        "per_board": per_board,
    }
    # Persist an audit row so ops can query sweep history without re-running.
    try:
        await core_db.get_db().lifecycle_sweep_runs.insert_one(dict(summary))
    except Exception:
        log.warning("lifecycle_sweep audit insert failed", exc_info=True)
    return summary
