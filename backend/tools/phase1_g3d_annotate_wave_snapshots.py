"""Phase 1 · G3d annotation migration (one-shot, idempotent).

Purpose
-------
Attach an IMMUTABLE `consents_snapshot_correction` annotation to every
`wave_authorizations` row whose original `consents_snapshot` fell through
empty due to the pre-fix schema-drift bug in
`domains.wave._snapshot_consents` (fixed 2026-08-06, commit 903af9e4).

Contract
--------
* NEVER modifies `consents_snapshot` (the original defective value stays
  on the row — append-only rule).
* Appends `consents_snapshot_correction`:
    {
      "original": {},                         # verbatim copy of the wrong value
      "corrected": {scope: "granted" | "revoked", ...},  # from live consent_records
      "corrected_at": "<iso utc>",
      "reason": "phase-1-g3d-fix: ...",
      "source": "phase1_g3d_annotate_wave_snapshots"
    }
* Idempotent: rows that already carry the annotation are skipped.
* Safe on empty preview state (no-op when there are 0 defective rows).

Rails
-----
* Preview-only. Consent snapshots are per-user data; the migration reads
  the CURRENT `consent_records` state to derive the correction. In
  preview that is safe because:
    - the only affected user is the fixture user
    - fixture scopes are set once at seed time and never revoked
  A production run would additionally require a point-in-time lookup
  (using `ts <= authorized_at`), which we implement here for correctness
  even in the preview no-op case.

Usage
-----
    cd /app/backend && python3 tools/phase1_g3d_annotate_wave_snapshots.py

Emits a JSON summary to stdout and to
/app/docs/phase-1-artifacts/g3d_annotation_summary.json
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import get_db
from core.time_utils import utc_now


ARTIFACT_PATH = Path("/app/docs/phase-1-artifacts/g3d_annotation_summary.json")


async def _point_in_time_snapshot(user_id: str, authorized_at) -> dict:
    """Return {scope → 'granted'|'revoked'} using ONLY `consent_records`
    rows whose `ts <= authorized_at`. Latest per scope wins.

    Matches the corrected `_snapshot_consents` reader, but with a
    point-in-time cutoff so historical audits are faithful.
    """
    db = get_db()
    out: dict[str, str] = {}
    query = {"user_id": user_id}
    if authorized_at is not None:
        query["ts"] = {"$lte": authorized_at}
    async for r in db.consent_records.find(
        query,
        {"_id": 0, "scope": 1, "granted": 1, "ts": 1},
    ).sort("ts", 1):
        scope = r.get("scope")
        if not scope:
            continue
        granted = r.get("granted")
        if granted is None:
            granted = bool(r.get("granted_at") and not r.get("revoked_at"))
        out[scope] = "granted" if granted else "revoked"
    return out


# The seeder re-baselines fixture-ead@ on every backend startup, wiping
# and re-inserting `consent_records` with all 6 scopes granted. This
# means historical rows written by earlier rebases have been cycled out.
# For those rows we can only reconstruct via the fixture invariant.
_FIXTURE_INVARIANT_SCOPES = {
    "discover_jobs": "granted",
    "email_me": "granted",
    "generate_materials": "granted",
    "process_career_data": "granted",
    "submit_applications": "granted",
    "track_applications": "granted",
}
_FIXTURE_EMAIL = "fixture-ead@opportunityos.dev"


async def _reconstruct_snapshot(user_id: str, authorized_at) -> tuple[dict, str]:
    """Return (snapshot, source) — try strict point-in-time first, then
    fall back to the fixture invariant if that user is the seeded fixture
    (whose historical consent_records were wiped by later rebases).
    Never fabricates for non-fixture users."""
    pit = await _point_in_time_snapshot(user_id, authorized_at)
    if pit:
        return pit, "consent_records_point_in_time"
    db = get_db()
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "email": 1})
    if user and user.get("email") == _FIXTURE_EMAIL:
        return dict(_FIXTURE_INVARIANT_SCOPES), (
            "fixture_invariant_fallback (historical consent_records "
            "cycled out by seed rebases; fixture invariant is all-6-granted)"
        )
    return {}, "no_data_recoverable"


async def run() -> dict:
    db = get_db()
    summary = {
        "run_at": utc_now().isoformat(),
        "reason": (
            "phase-1-g3d-fix: `_snapshot_consents` reader in "
            "`domains/wave/__init__.py` was addressing legacy field names "
            "(`status` / `granted_at` / `revoked_at`) that never existed "
            "in the Phase-6-hardened `consent_records` schema (correct: "
            "`granted: bool` + `ts: datetime`). Every projected value "
            "collapsed to falsy, so the returned dict fell through empty "
            "for every scope the user had actually granted. Bug class: "
            "schema drift after a hardening pass that didn't sweep all "
            "readers."
        ),
        "candidates_scanned": 0,
        "already_annotated_skipped": 0,
        "annotated_now": 0,
        "annotated_rows": [],
    }

    # Only sweep rows with an EMPTY / MISSING consents_snapshot (defective
    # by construction of the pre-fix code path). Post-fix rows have a
    # non-empty dict, so this predicate is safe.
    cursor = db.wave_authorizations.find(
        {"$or": [{"consents_snapshot": {}}, {"consents_snapshot": {"$exists": False}}]},
        {"_id": 0}
    )
    async for row in cursor:
        summary["candidates_scanned"] += 1
        if row.get("consents_snapshot_correction"):
            summary["already_annotated_skipped"] += 1
            continue
        corrected, source = await _reconstruct_snapshot(
            row["user_id"], row.get("authorized_at"))
        annotation = {
            "original": row.get("consents_snapshot") or {},
            "corrected": corrected,
            "corrected_source": source,
            "corrected_at": utc_now().isoformat(),
            "reason": summary["reason"],
            "source": "phase1_g3d_annotate_wave_snapshots",
        }
        await db.wave_authorizations.update_one(
            {"id": row["id"]},
            {"$set": {"consents_snapshot_correction": annotation}}
        )
        summary["annotated_now"] += 1
        summary["annotated_rows"].append({
            "id": row["id"],
            "user_id": row["user_id"],
            "triggered_by": row.get("triggered_by"),
            "authorized_at": (
                row["authorized_at"].isoformat()
                if isinstance(row.get("authorized_at"), datetime)
                else row.get("authorized_at")
            ),
            "corrected": corrected,
            "corrected_source": source,
        })

    # Emit a queryability aid — index the annotation timestamp so
    # future audits can filter fast.
    try:
        await db.wave_authorizations.create_index(
            "consents_snapshot_correction.corrected_at",
            name="wave_g3d_correction_ts",
            sparse=True,
        )
        summary["index_ensured"] = "consents_snapshot_correction.corrected_at (sparse)"
    except Exception as e:
        summary["index_ensured"] = f"error: {e!r}"

    ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    asyncio.run(run())
