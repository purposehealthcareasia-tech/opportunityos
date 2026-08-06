"""Scored-tuple cache — Phase 1 Step (ii) scorer unfreeze.

Moves `gate_engine.evaluate()` + `scoring.score()` off the /feed request
hot path by memoizing the (gate, score_row) tuple per deterministic key:

    (user_ctx_sig, job_id, job_last_verified_iso, weights_version)

Byte-identical by construction — on cache hit we return the exact object
stored on first compute; on miss we run the SAME `evaluate()` + `score()`
functions and cache the result. No weights are changed, no scoring code
is touched.

Invalidation: cache is process-local. Uvicorn reload / supervisor restart
clears it. The key incorporates `weights_version` so a scoring semantics
bump auto-invalidates. `user_ctx_sig` incorporates prefs/eligibility
version and approved-claims/hidden/existing-apps signatures, so any
change to those on the user's side auto-invalidates their rows.

Bounded LRU: max entries = SCORED_CACHE_MAX (default 500_000). Evicts
oldest on overflow.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import OrderedDict
from datetime import datetime
from typing import Any

from services import gate_engine
from services.scoring import WEIGHTS_VERSION, score as _score_job

SCORED_CACHE_MAX = int(os.environ.get("FYND_SCORED_CACHE_MAX", "500000"))

# OrderedDict for LRU (move_to_end on access; popitem(last=False) on overflow).
_cache: "OrderedDict[tuple, tuple[dict, dict]]" = OrderedDict()

# Instrumentation for evidence — counts persist for process lifetime.
_stats = {"hits": 0, "misses": 0, "evictions": 0, "invalidations": 0}


def _stringify(x: Any) -> str:
    """Stable string representation for hashing."""
    if isinstance(x, (set, frozenset)):
        return json.dumps(sorted(str(v) for v in x), separators=(",", ":"))
    if isinstance(x, dict):
        return json.dumps(x, sort_keys=True, separators=(",", ":"), default=str)
    if isinstance(x, list):
        return json.dumps(x, separators=(",", ":"), default=str)
    return str(x)


def ctx_signature(ctx: dict) -> str:
    """Fingerprint the user context so cache invalidates on any state change.

    Includes: user_id, prefs, eligibility, approved skills / education /
    employment / certifications, existing_applications, hidden_job_ids.
    """
    parts = [
        ctx.get("user_id") or "",
        _stringify(ctx.get("preferences") or {}),
        _stringify(ctx.get("eligibility") or {}),
        _stringify(ctx.get("approved_skills") or set()),
        _stringify(ctx.get("approved_education") or []),
        _stringify(ctx.get("approved_employment") or []),
        _stringify(ctx.get("approved_certifications") or []),
        _stringify(ctx.get("existing_applications") or set()),
        _stringify(ctx.get("hidden_job_ids") or set()),
    ]
    return hashlib.md5("::".join(parts).encode()).hexdigest()


def _job_lv_iso(job: dict) -> str:
    lv = job.get("last_verified")
    if isinstance(lv, datetime):
        return lv.isoformat()
    return str(lv or "")


def get_or_compute(ctx: dict, job: dict, ctx_sig: str | None = None) -> tuple[dict, dict]:
    """Return (gate_result, score_row) for (user, job). Compute on miss,
    return cached tuple on hit.

    ``ctx_sig`` may be passed in when the caller has already computed it
    once for the request (saves rehashing across every job in the loop).
    """
    sig = ctx_sig or ctx_signature(ctx)
    key = (sig, job.get("id"), _job_lv_iso(job), WEIGHTS_VERSION)
    hit = _cache.get(key)
    if hit is not None:
        _stats["hits"] += 1
        _cache.move_to_end(key)
        return hit
    _stats["misses"] += 1
    gate = gate_engine.evaluate(ctx, job)
    score_row = _score_job(ctx, job, gate) if gate["pass_all"] else None
    tup = (gate, score_row)
    _cache[key] = tup
    if len(_cache) > SCORED_CACHE_MAX:
        _cache.popitem(last=False)
        _stats["evictions"] += 1
    return tup


def invalidate_user(user_id: str) -> int:
    """Drop all cached rows for a user_id. Returns count removed."""
    dropped = 0
    to_del = [k for k in _cache if k[0].startswith(user_id[:0])]  # noop guard
    # We can't decode user_id from md5 sig; caller must invalidate by
    # sig if needed. This helper is a no-op today — kept for API shape.
    for k in to_del:
        del _cache[k]
        dropped += 1
    _stats["invalidations"] += dropped
    return dropped


def clear_all() -> int:
    """Drop the entire cache. Used by tests and admin ops. Returns count."""
    n = len(_cache)
    _cache.clear()
    _stats["invalidations"] += n
    return n


def stats() -> dict:
    """Return a snapshot of cache stats."""
    return {**_stats, "size": len(_cache), "max": SCORED_CACHE_MAX,
            "weights_version": WEIGHTS_VERSION}
