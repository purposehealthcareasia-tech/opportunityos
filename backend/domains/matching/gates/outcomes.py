"""Stage 1 gate outcomes.

FYND ATLAS mandates FOUR outcomes (not three). The fourth,
`candidate_confirmation_required`, exists so the platform never
fabricates a `pass` or a `fail` when the deciding fact is a candidate
statement the platform has not received. Example: a US-federal-only
role plus a candidate whose work-auth status is empty. The correct
outcome is NOT `fail` (that would over-filter) and NOT `unknown`
(that would surface as an unclear NOTE); it is
`candidate_confirmation_required`, so the UI can prompt for the
missing fact and re-run the gate.

Order matters:
  * `fail` is terminal for the gate group (the opportunity cannot
    proceed to Stage 2 on a `fail`).
  * `candidate_confirmation_required` blocks scoring but is
    resolvable by the candidate.
  * `unknown` surfaces as a NOTE but is not terminal.
  * `pass` clears the gate.
"""
from __future__ import annotations

from enum import Enum


class GateOutcome(str, Enum):
    """The FOUR permitted Stage 1 gate outcomes.

    Encoded as `str, Enum` so JSON serialization is free and comparisons
    with string literals in tests remain safe.
    """
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"
    CANDIDATE_CONFIRMATION_REQUIRED = "candidate_confirmation_required"

    @property
    def is_terminal_fail(self) -> bool:
        """`fail` is the ONLY terminal outcome; Stage 2 must not run
        for any gate that returned `fail`."""
        return self is GateOutcome.FAIL
