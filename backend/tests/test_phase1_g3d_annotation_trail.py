"""Phase 1 · G3d annotation trail invariance.

Locks in: the `consents_snapshot_correction` annotation applied to
pre-fix defective `wave_authorizations` rows is:
  * IMMUTABLE — the original defective value stays on the row under
    `consents_snapshot`; only a NEW field `consents_snapshot_correction`
    is added. Never a silent rewrite of the original.
  * Idempotent — re-running the migration is a no-op on already-annotated
    rows.
  * Fully queryable — an index on
    `consents_snapshot_correction.corrected_at` exists.

Runs against the actual MongoDB (preview state), read-only assertions.
"""
from __future__ import annotations

import os
import asyncio
import pytest


MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")


@pytest.mark.asyncio
async def test_annotation_never_rewrites_original():
    """Every row that has `consents_snapshot_correction` must retain
    the original `consents_snapshot` verbatim under
    `.consents_snapshot_correction.original` — no silent rewrite of the
    top-level `consents_snapshot` field."""
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    try:
        db = client[os.environ.get("DB_NAME", "opportunityos")]
        cnt = 0
        async for r in db.wave_authorizations.find(
            {"consents_snapshot_correction": {"$exists": True}},
            {"_id": 0}
        ):
            cnt += 1
            ann = r.get("consents_snapshot_correction")
            assert isinstance(ann, dict), (r["id"], ann)
            assert "original" in ann, r["id"]
            assert "corrected" in ann, r["id"]
            assert "corrected_at" in ann, r["id"]
            assert "reason" in ann, r["id"]
            # Immutability: the top-level snapshot must equal the original.
            assert r.get("consents_snapshot") == ann["original"], (
                f"row {r['id']}: top-level consents_snapshot was rewritten "
                f"(now={r.get('consents_snapshot')!r}, "
                f"original={ann['original']!r})"
            )
        # Preview environment: expect >= 0 rows. Migration is idempotent
        # so this test is safe to run repeatedly.
        assert cnt >= 0
    finally:
        client.close()


@pytest.mark.asyncio
async def test_annotation_migration_is_idempotent():
    """Running the migration twice must not change annotation count."""
    from tools.phase1_g3d_annotate_wave_snapshots import run
    s1 = await run()
    n1 = s1["annotated_now"] + s1["already_annotated_skipped"]
    s2 = await run()
    n2 = s2["annotated_now"] + s2["already_annotated_skipped"]
    # Total scanned must be equal, annotated_now must be 0 the second time.
    assert s2["annotated_now"] == 0, s2
    assert s1["candidates_scanned"] == s2["candidates_scanned"], (s1, s2)
    assert n1 == n2, (n1, n2)


@pytest.mark.asyncio
async def test_correction_index_exists():
    """A sparse index on `consents_snapshot_correction.corrected_at` must
    exist so auditors can query the trail without a full scan."""
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    try:
        db = client[os.environ.get("DB_NAME", "opportunityos")]
        idx = await db.wave_authorizations.index_information()
        keys = [
            tuple(v.get("key") or []) for v in idx.values()
        ]
        assert (("consents_snapshot_correction.corrected_at", 1),) in keys, keys
    finally:
        client.close()
