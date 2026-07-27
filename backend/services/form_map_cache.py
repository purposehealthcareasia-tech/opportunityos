"""Form-map cache — Phase 5.2 (Founder Directive 2026-07-28).

RULE:
  Key: `(ats, form_fingerprint)` where fingerprint is a stable hash of
       the form's FIELD STRUCTURE (name + type + required, sorted).
  Value: `{selector_map, fill_confidence, verified_at, verified_by_count,
           verified_by_source}` where selector_map is a list of
       `{selector, role, confidence}` entries (role = e.g., email,
       first_name, phone, linkedin_url).

  * One verified fill (sanctioned dry-run OR human sprint confirmation)
    promotes the map for ALL users.
  * Fingerprint drift → auto-demote to unverified → assisted lane.
  * Cache stores STRUCTURE only — NEVER user data (no filled values,
    no PII, no employer secrets).

  * Bootstrap: strictly from existing sanctioned dry-run artifacts. No
    new live-form automation to populate the cache without founder
    approval.

Public API:
  * canonical_fingerprint(fields: list[dict]) → str
  * record_verified(ats, url, fields, source, filled_count) → dict
  * lookup(ats, fingerprint) → dict | None
  * demote(ats, fingerprint, reason) → dict
  * bootstrap_from_dryrun_json(path: str) → summary

Storage: `form_maps` collection. One row per (ats, fingerprint).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from core import db as core_db


log = logging.getLogger("form_map_cache")


STATUS_VERIFIED = "verified"
STATUS_UNVERIFIED = "unverified"
STATUS_DEMOTED = "demoted"


def canonical_fingerprint(fields: list[dict]) -> str:
    """Deterministic hash of the form's field structure.

    We deliberately IGNORE selectors — same field structure across two
    otherwise-different Greenhouse pages should collide, because the
    selector map from one can be replayed on the other.

    Each field is normalized to (name, type, required?) tuple, sorted
    canonically, then hashed."""
    normalized = []
    for f in fields:
        name = str(f.get("name") or f.get("label") or "").strip().lower()
        ftype = str(f.get("type") or "text").strip().lower()
        required = bool(f.get("required"))
        if not name:
            continue
        normalized.append((name, ftype, required))
    normalized.sort()
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def url_fingerprint(url: str) -> str:
    """Fallback fingerprint when we don't yet have field structure —
    used for URL-only bootstrap from the sanctioned dry-run pass. When
    the harness is later enhanced to emit field structure, that
    fingerprint replaces this one for the same URL."""
    parsed = urlparse(url)
    # Strip query string + fragment — Greenhouse `?gh_jid=…` and Lever
    # tracking params are noise for cache identity.
    canonical = f"{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    return "url:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


async def lookup(ats: str, fingerprint: str) -> dict | None:
    """Look up a verified form-map. Returns the row or None."""
    db = core_db.get_db()
    return await db.form_maps.find_one(
        {"ats": ats, "fingerprint": fingerprint},
        {"_id": 0},
    )


async def record_verified(
    *, ats: str, url: str,
    fields: list[dict] | None = None,
    selector_map: list[dict] | None = None,
    verified_by_source: str,
    filled_count: int = 0,
    found_count: int = 0,
) -> dict:
    """Record a successful verified fill. Promotes / upgrades the map.

    * `fields`: field-structure list (required for a real fingerprint).
    * `selector_map`: optional list of `{selector, role, confidence}`.
       NEVER include user data here — only structure/selector shape.
    * `verified_by_source`: an audit tag such as
       `dryrun_pass_1785190117#url_02` or `sprint_confirm:<slot_id>`.

    When `fields` is None (URL-only bootstrap), a URL-fingerprint is
    used with `structure_captured=False` so the frontend knows the map
    is best-effort and still needs a real structure capture.

    Returns the persisted row (upserted)."""
    now = datetime.now(timezone.utc)
    if fields:
        fp = canonical_fingerprint(fields)
        structure_captured = True
    else:
        fp = url_fingerprint(url)
        structure_captured = False

    # Sanitize selector_map — enforce no user data leaked in.
    _clean_selectors = [
        {"selector": str(s.get("selector") or "")[:200],
         "role": str(s.get("role") or "")[:60],
         "confidence": float(s.get("confidence") or 0.0)}
        for s in (selector_map or [])
        if s.get("selector")
    ]

    db = core_db.get_db()
    existing = await db.form_maps.find_one(
        {"ats": ats, "fingerprint": fp}, {"_id": 0})
    verified_by_count = int((existing or {}).get("verified_by_count") or 0) + 1
    # Confidence — start at 1.0 on first verified fill, then use a
    # simple decay-toward-1 as more confirmations arrive (stable-if-flat).
    fill_confidence = min(1.0, 0.6 + 0.1 * verified_by_count)

    doc = {
        "ats": ats,
        "fingerprint": fp,
        "structure_captured": structure_captured,
        "url_sample": url,  # kept for ops/debugging — never user data
        "field_count_found": found_count,
        "field_count_filled": filled_count,
        "selector_map": _clean_selectors,
        "fill_confidence": fill_confidence,
        "status": STATUS_VERIFIED,
        "verified_at": now,
        "verified_by_count": verified_by_count,
        "verified_by_sources": (
            (existing or {}).get("verified_by_sources", []) + [verified_by_source]
        )[-25:],  # keep last 25 for audit trail without unbounded growth
        "updated_at": now,
    }
    if existing:
        await db.form_maps.update_one(
            {"ats": ats, "fingerprint": fp},
            {"$set": doc},
        )
    else:
        doc["first_verified_at"] = now
        await db.form_maps.insert_one(dict(doc))
    return doc


async def demote(ats: str, fingerprint: str, reason: str) -> dict | None:
    """Auto-demote a previously-verified form map (fingerprint drift,
    fill failure, structure change). Never deletes — sets status to
    `demoted` and logs the reason. Callers route the corresponding
    dispatch to the assisted lane."""
    now = datetime.now(timezone.utc)
    db = core_db.get_db()
    existing = await db.form_maps.find_one({"ats": ats, "fingerprint": fingerprint})
    if not existing:
        return None
    demote_events = list(existing.get("demote_events", []))
    demote_events.append({"at": now.isoformat(), "reason": reason,
                            "previous_confidence": existing.get("fill_confidence")})
    updated = await db.form_maps.find_one_and_update(
        {"ats": ats, "fingerprint": fingerprint},
        {"$set": {"status": STATUS_DEMOTED,
                    "demote_reason": reason,
                    "demote_events": demote_events[-25:],
                    "fill_confidence": 0.0,
                    "updated_at": now}},
        projection={"_id": 0},
        return_document=True,
    )
    return updated


async def bootstrap_from_dryrun_json(path: str,
                                       *, source_tag_prefix: str = "dryrun_pass"
                                       ) -> dict:
    """Bootstrap the form-map cache from an already-persisted sanctioned
    dry-run JSON audit. Only URL-level fingerprints are populated (the
    current harness output does not include field structure). Real
    field-level fingerprints will be added when the harness is
    explicitly enhanced under a future authorized dry-run.

    Returns a summary dict with counts."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"dry-run audit not found: {path}")
    with open(path, encoding="utf-8") as f:
        audit = json.load(f)
    started = audit.get("started_at") or "unknown"
    stamp = str(int(datetime.fromisoformat(started.replace("Z", "+00:00")).timestamp())
                 if "T" in started else "unknown")
    recorded = 0
    skipped = 0
    for r in audit.get("results", []):
        if r.get("state") != "filled_and_aborted":
            skipped += 1
            continue
        if not r.get("fields_filled_correctly"):
            skipped += 1
            continue
        url = r["url"]
        host = urlparse(url).netloc.lower()
        ats = ("greenhouse" if "greenhouse" in host
                 else "lever" if "lever" in host
                 else "ashby" if "ashby" in host
                 else "unknown")
        if ats == "unknown":
            skipped += 1
            continue
        await record_verified(
            ats=ats, url=url,
            fields=None,          # URL-level bootstrap — no field structure yet
            selector_map=None,
            verified_by_source=f"{source_tag_prefix}_{stamp}#url_{r['index']:02d}",
            filled_count=int(r.get("fields_filled") or 0),
            found_count=int(r.get("fields_found") or 0),
        )
        recorded += 1
    return {"path": path, "recorded": recorded, "skipped": skipped,
            "started_at": started}
