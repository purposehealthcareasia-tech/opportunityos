"""materials_hash — sha256 over the canonical payload the user is authorizing us to send.

Phase 5 rule (founder brief §B): the authorization is scoped to a specific SNAPSHOT
of the materials. If the user edits the resume or a screener answer after approving,
the hash mismatches and submit is blocked with a "materials changed — re-approval
required" error.

Canonical shape (sorted, JSON-dumped, sha256'd):
  {
    "resume_lines": [ {"line_id": "...", "text": "...", "claim_ids": ["..."]}, ... ],
    "screeners":    [ {"question_id": "...", "answer": "...", "approved": true}, ... ],
  }

Only ACCEPTED resume lines and answered-and-approved screeners contribute. Everything
else is irrelevant to the signed packet.
"""
from __future__ import annotations
import hashlib
import json
from typing import Any


def compute(*, accepted_lines: list[dict[str, Any]], approved_answers: list[dict[str, Any]]) -> str:
    """Return hex sha256 of the canonical materials JSON."""
    payload = {
        "resume_lines": sorted(
            [
                {
                    "line_id": str(L.get("line_id") or ""),
                    "text": (L.get("text") or "").strip(),
                    "claim_ids": sorted(list(L.get("claim_ids") or [])),
                }
                for L in accepted_lines or []
            ],
            key=lambda x: x["line_id"],
        ),
        "screeners": sorted(
            [
                {
                    "question_id": str(a.get("question_id") or ""),
                    "answer": (a.get("answer") or "").strip(),
                    "approved": bool(a.get("approved")),
                }
                for a in approved_answers or []
            ],
            key=lambda x: x["question_id"],
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
