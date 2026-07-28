"""ingest_form_maps.py — populate `form_maps` from a sanctioned dry-run.

Founder Directive (2026-07-28 · Item 4): after a sanctioned fill-and-abort
pass emits `captured_fields` and `captured_selectors` per URL, this tool
ingests those into the shared form-map cache with real field-structure
fingerprints (`structure_captured=True`).

Rails:
  * READ-ONLY on the browser side — no re-fetch, no re-fill; just reads
    the machine-readable JSON audit that the harness already wrote.
  * WRITE side ONLY into `form_maps` via
    `services.form_map_cache.record_verified()`. Never touches employers.
  * PII scan after ingest: fails hard and reports any doc that contains a
    value-shaped field, an obvious raw email, or one of the fixture
    identity tokens. If the scan is not null, the caller purges the
    just-ingested docs and reports the leak.

Invocation (founder-authorized only):
  python3 /app/backend/tools/ingest_form_maps.py \\
      --audit /app/docs/dryrun-screenshots/dryrun_<ts>.json \\
      [--purge-on-leak]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, "/app/backend")

from services import form_map_cache


# PII tokens we must never see in a form-map doc.
_FIXTURE_TOKENS = (
    "fixture-dryrun",
    "opportunityos.dev",
    "fixture testuser",
    "fixturetestuser",
    "555-0100",
    "linkedin.com/in/fixture",
    "phoenix, az",
    "fixture-ead",
)
_FORBIDDEN_SELECTOR_KEYS = {
    "value", "values", "user_input", "answer", "answers",
    "resume_text", "filled_value", "user_data", "resume",
    "email_value", "phone_value", "name_value",
}
_EMAIL_RX = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def _detect_ats(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if "greenhouse" in host:
        return "greenhouse"
    if "lever" in host:
        return "lever"
    if "ashby" in host:
        return "ashby"
    return "unknown"


def _pii_scan_doc(doc: dict) -> list[str]:
    """Return a list of stringified violations for this doc (empty = clean)."""
    hits: list[str] = []
    payload = json.dumps(doc, default=str).lower()
    for tok in _FIXTURE_TOKENS:
        if tok in payload:
            hits.append(f"fixture_token:{tok}")
    for sel in doc.get("selector_map") or []:
        if not isinstance(sel, dict):
            continue
        for k in sel.keys():
            if k.lower() in _FORBIDDEN_SELECTOR_KEYS:
                hits.append(f"forbidden_selector_key:{k}")
    # Scan any non-audit string field for raw email addresses.
    audit_keys = {"url_sample", "verified_by_sources"}
    for k, v in doc.items():
        if k in audit_keys:
            continue
        if isinstance(v, str) and _EMAIL_RX.search(v):
            hits.append(f"email_in_field:{k}")
    return hits


async def _ingest(audit_path: Path, *, purge_on_leak: bool = False) -> dict:
    if not audit_path.exists():
        raise FileNotFoundError(f"audit not found: {audit_path}")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    tag_stamp = str(int(
        (audit.get("started_at") or "").replace(":", "-").replace("Z", "")[0:19]
        .replace("T", "").replace("-", "")
    ) or 0) or audit_path.stem

    inserted_or_updated: list[dict] = []
    skipped: list[dict] = []
    for r in audit.get("results", []):
        if r.get("state") != "filled_and_aborted":
            skipped.append({"index": r.get("index"), "reason": r.get("state")})
            continue
        fields = r.get("captured_fields") or []
        selectors = r.get("captured_selectors") or []
        if not fields:
            skipped.append({"index": r.get("index"), "reason": "no_captured_fields"})
            continue
        ats = _detect_ats(r["url"])
        if ats == "unknown":
            skipped.append({"index": r.get("index"), "reason": "unknown_ats"})
            continue
        row = await form_map_cache.record_verified(
            ats=ats, url=r["url"],
            fields=fields,
            selector_map=selectors,
            verified_by_source=f"dryrun_pass_{tag_stamp}#url_{r['index']:02d}",
            filled_count=int(r.get("fields_filled") or 0),
            found_count=int(r.get("fields_found") or 0),
        )
        inserted_or_updated.append({
            "index": r["index"], "url": r["url"],
            "ats": ats, "fingerprint": row["fingerprint"],
            "field_count": len(fields),
            "structure_captured": row.get("structure_captured"),
        })

    # Post-ingest PII scan — every doc touched by this pass.
    from core.db import get_db
    db = get_db()
    fingerprints = {(row["ats"], row["fingerprint"]) for row in inserted_or_updated}
    scan_hits: list[dict] = []
    async for doc in db.form_maps.find({}):
        doc_key = (doc.get("ats"), doc.get("fingerprint"))
        hits = _pii_scan_doc(doc)
        if hits:
            scan_hits.append({
                "ats": doc.get("ats"),
                "fingerprint": doc.get("fingerprint"),
                "hits": hits,
                "was_just_ingested": doc_key in fingerprints,
            })

    result = {
        "audit_path": str(audit_path),
        "ingested_or_updated": len(inserted_or_updated),
        "skipped": len(skipped),
        "skipped_detail": skipped[:10],
        "pii_scan": {
            "clean": len(scan_hits) == 0,
            "hits": scan_hits,
        },
        "structure_captured_true_after_ingest":
            await db.form_maps.count_documents({"structure_captured": True}),
        "structure_captured_false_after_ingest":
            await db.form_maps.count_documents({"structure_captured": False}),
    }

    if scan_hits and purge_on_leak:
        # Purge only the newly-ingested docs. Never touch existing clean rows.
        purged: list[dict] = []
        for hit in scan_hits:
            if not hit["was_just_ingested"]:
                continue
            del_res = await db.form_maps.delete_one({
                "ats": hit["ats"], "fingerprint": hit["fingerprint"],
            })
            purged.append({"ats": hit["ats"], "fingerprint": hit["fingerprint"],
                             "deleted": del_res.deleted_count})
        result["purged_leaking_docs"] = purged

    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=(
        "Ingest sanctioned dry-run captured_fields into form_maps."
    ))
    ap.add_argument("--audit", required=True,
                    help="Path to dryrun_<ts>.json emitted by fill_and_abort.py")
    ap.add_argument("--purge-on-leak", action="store_true",
                    help="If PII scan finds any newly-ingested leaky doc, delete it.")
    args = ap.parse_args()
    summary = asyncio.run(_ingest(Path(args.audit),
                                     purge_on_leak=args.purge_on_leak))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
