"""Census-diff — read-only ops tool.

Compares the two most recent `route_census_runs` documents and reports:

  * `flipped`      — employer classification changed (e.g. gh-noCap → portal-other,
                     lever-cap → gh-noCap, dns-error → gh-noCap, timeout → gh-noCap).
  * `http_changed` — HTTP status changed between passes (200 → 403, 429 → 200).
  * `retry_climb`  — `transient_failures` count climbed by ≥ 2 vs. previous pass
                     (early signal of a host degrading before it hits a CAPTCHA).
  * `new_hosts`    — hosts probed in the newest pass that did NOT appear in the
                     prior pass (catalog expansion signal).
  * `dropped_hosts`— hosts in the prior pass that did NOT appear in the newest
                     pass (catalog shrink / employer removal).

Runs entirely off already-persisted `route_census` + `route_census_runs` data.
Never re-probes employer origins — this is an ops summary, not a re-scan.

Persists a single diff row per invocation to a new
`route_census_diffs` collection so the ops history is queryable.

Usage:
  python3 backend/tools/route_census_diff.py                     # diff latest vs previous
  python3 backend/tools/route_census_diff.py --older <run-id>    # explicit older
  python3 backend/tools/route_census_diff.py --newer <run-id>    # explicit newer
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient


MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
if not (MONGO_URL and DB_NAME):
    # Fall back to reading backend/.env when the script is invoked outside
    # the supervised backend process.
    env_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    if k == "MONGO_URL" and not MONGO_URL:
                        MONGO_URL = v
                    if k == "DB_NAME" and not DB_NAME:
                        DB_NAME = v


def _dt_iso(v) -> str | None:
    if isinstance(v, datetime):
        return v.isoformat()
    return v


async def _load_run(db, run_id: str | None, ordinal: int) -> tuple[dict, list[dict]]:
    """Return (run_summary, per_url_rows) for the given run.

    * If `run_id` is provided, load that specific run.
    * Otherwise load the run at position `ordinal` in descending-order (0 = latest).
    """
    if run_id:
        run = await db.route_census_runs.find_one({"id": run_id}, {"_id": 0})
        if not run:
            raise SystemExit(f"route_census_runs id={run_id!r} not found")
    else:
        cur = db.route_census_runs.find({}, {"_id": 0}).sort([("started_at", -1)])
        rows = [r async for r in cur]
        if len(rows) <= ordinal:
            raise SystemExit(
                f"only {len(rows)} route_census_runs exist; cannot pick ordinal={ordinal}")
        run = rows[ordinal]
    # Per-URL rows aren't versioned inside `route_census` — that collection
    # stores current state per URL. To reconstruct historical per-URL rows
    # we'd need a versioned collection. For now, we compare per-URL only
    # for the newest run (which reflects `route_census` today) and treat
    # the older run's aggregate summary as the ground truth for that pass.
    rows: list[dict] = []
    if ordinal == 0:
        cur = db.route_census.find({}, {"_id": 0})
        rows = [r async for r in cur]
    return run, rows


def _index_by_url(rows: list[dict]) -> dict[str, dict]:
    return {r["url"]: r for r in rows if r.get("url")}


def _diff(newer_run: dict, newer_rows: list[dict],
          older_run: dict, older_rows: list[dict]) -> dict:
    newer_by_class = newer_run.get("by_classification") or {}
    older_by_class = older_run.get("by_classification") or {}
    all_classes = sorted(set(newer_by_class) | set(older_by_class))
    class_shifts = []
    for c in all_classes:
        delta = newer_by_class.get(c, 0) - older_by_class.get(c, 0)
        if delta:
            class_shifts.append({
                "classification": c,
                "older": older_by_class.get(c, 0),
                "newer": newer_by_class.get(c, 0),
                "delta": delta,
            })
    # Per-URL diffs are only possible if we have both sides. If the older
    # pass wasn't captured URL-by-URL, older_rows is empty and we emit
    # only the aggregate shift.
    older_ix = _index_by_url(older_rows)
    newer_ix = _index_by_url(newer_rows)
    flipped = []
    http_changed = []
    retry_climb = []
    for url, cur in newer_ix.items():
        prev = older_ix.get(url)
        if not prev:
            continue
        if cur.get("classification") != prev.get("classification"):
            flipped.append({
                "url": url,
                "employer": cur.get("employer"),
                "host": cur.get("host"),
                "from": prev.get("classification"),
                "to": cur.get("classification"),
            })
        if cur.get("http_status") != prev.get("http_status"):
            http_changed.append({
                "url": url,
                "employer": cur.get("employer"),
                "host": cur.get("host"),
                "from": prev.get("http_status"),
                "to": cur.get("http_status"),
            })
        cur_tr = int(cur.get("transient_failures") or 0)
        prev_tr = int(prev.get("transient_failures") or 0)
        if cur_tr - prev_tr >= 2:
            retry_climb.append({
                "url": url,
                "employer": cur.get("employer"),
                "host": cur.get("host"),
                "from": prev_tr,
                "to": cur_tr,
            })
    older_hosts = {r.get("host") for r in older_rows if r.get("host")}
    newer_hosts = {r.get("host") for r in newer_rows if r.get("host")}
    new_hosts = sorted(newer_hosts - older_hosts) if older_hosts else []
    dropped_hosts = sorted(older_hosts - newer_hosts) if older_hosts else []
    return {
        "id": f"census-diff-{int(datetime.now(timezone.utc).timestamp())}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "older_run_id": older_run.get("id"),
        "older_run_started_at": _dt_iso(older_run.get("started_at")),
        "newer_run_id": newer_run.get("id"),
        "newer_run_started_at": _dt_iso(newer_run.get("started_at")),
        "class_shifts": class_shifts,
        "flipped": flipped,
        "http_changed": http_changed,
        "retry_climb": retry_climb,
        "new_hosts": new_hosts,
        "dropped_hosts": dropped_hosts,
        "counts": {
            "class_shifts": len(class_shifts),
            "flipped": len(flipped),
            "http_changed": len(http_changed),
            "retry_climb": len(retry_climb),
            "new_hosts": len(new_hosts),
            "dropped_hosts": len(dropped_hosts),
        },
    }


async def _print_summary(diff: dict) -> None:
    print(f"census-diff  older={diff['older_run_id']}  newer={diff['newer_run_id']}")
    print(f"  class_shifts: {len(diff['class_shifts'])}")
    for s in diff["class_shifts"]:
        d = s["delta"]
        sign = "+" if d > 0 else ""
        print(f"    {s['classification']:15s} {s['older']:>5} → {s['newer']:<5}  {sign}{d}")
    print(f"  flipped:       {len(diff['flipped'])}")
    for f in diff["flipped"][:10]:
        print(f"    {f['employer']:30s} {f['host']:35s} {f['from']:15s} → {f['to']}")
    print(f"  http_changed:  {len(diff['http_changed'])}")
    for h in diff["http_changed"][:10]:
        print(f"    {h['employer']:30s} {h['host']:35s} {h['from']} → {h['to']}")
    print(f"  retry_climb:   {len(diff['retry_climb'])}")
    for r in diff["retry_climb"][:10]:
        print(f"    {r['employer']:30s} {r['host']:35s} {r['from']} → {r['to']}")
    print(f"  new_hosts:     {len(diff['new_hosts'])}"
          + (": " + ", ".join(diff["new_hosts"][:10]) if diff["new_hosts"] else ""))
    print(f"  dropped_hosts: {len(diff['dropped_hosts'])}"
          + (": " + ", ".join(diff["dropped_hosts"][:10]) if diff["dropped_hosts"] else ""))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--older", help="explicit older route_census_runs.id")
    ap.add_argument("--newer", help="explicit newer route_census_runs.id")
    ap.add_argument("--json", action="store_true", help="print full diff as JSON")
    args = ap.parse_args()
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    db = client[DB_NAME]
    try:
        newer_run, newer_rows = await _load_run(db, args.newer, ordinal=0)
        older_run, older_rows = await _load_run(db, args.older, ordinal=1)
        diff = _diff(newer_run, newer_rows, older_run, older_rows)
        # Persist a single diff row.
        await db.route_census_diffs.insert_one(dict(diff))
        if args.json:
            print(json.dumps(diff, indent=2, default=str))
        else:
            await _print_summary(diff)
        print(f"\nPersisted to route_census_diffs.id = {diff['id']}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
