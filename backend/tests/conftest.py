"""Phase 3 regression tests.

Covers Founder-Directive compensating requirements:
- Unique-index proofs (canonical_key, submission_receipts, usage_meters)
- Atomic application state transitions (no race window)
- Gate engine parity between coverage-preview and feed
- Ingest auth semantics (401/403/503)
- 14-gate enumeration

Run:
    cd /app/backend && python3 -m pytest tests -v
"""
import os
import sys
from pathlib import Path

# So we can import `services.*`, `domains.*`, `core.*` from the /app/backend root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
