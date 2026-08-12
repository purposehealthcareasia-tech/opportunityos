"""Phase 6f · Autopilot auto-submit hard-lock.

Founder-directive-locked gate for autopilot form-route auto-submit.
Ships DISABLED per-user (`settings.autopilot_auto_submit_opt_in=False`).
Even if a user opts in, this gate MUST return `(True, "allowed")` before
any auto-submit fires — and it only returns True when both:

    1. `n_samples >= MIN_SAMPLE_SIZE`  (default 200)
    2. Wilson-CI 95% LOWER bound of accuracy >= MIN_ACCURACY  (default 0.99)

Rationale for MIN_SAMPLE_SIZE=200:
    MIN_SAMPLE_SIZE is the ADMISSION threshold to the accuracy check —
    below 200 fields we don't even measure. But passing that alone does
    NOT unlock: the Wilson-95% LOWER bound must ALSO clear MIN_ACCURACY.
    At p̂=1.0 the Wilson lower bound is n/(n+z²) with z≈1.96, so for
    lower >= 0.99 you need n >= ~381 fields. At p̂=0.99 you need
    substantially more. That's the intentional safety floor: perfect
    OBSERVED accuracy alone doesn't unlock — you need enough samples
    that a 95%-CI statistically rules out sub-99% TRUE accuracy. The
    layered design (sample-size ≥ 200 AND CI-lower ≥ 0.99) means neither
    a lucky short streak nor a single-outlier long streak can spoof
    the gate. Reason codes emitted by the gate make the block honest —
    the UI can render "insufficient_sample" vs "accuracy_below_threshold"
    with the exact metric values.

    (The earlier proposal of "n=200 gives ±1.4pp half-width" was for
    approximate Wilson centered on p̂=0.99; the actual Wilson LOWER
    bound at those coordinates is ≈0.964. Documented here so nobody
    revises MIN_SAMPLE_SIZE without re-doing the math.)

The threshold is a code constant (this file), NOT a doc. Founder can
tighten but not loosen without a signed-off code change; any UI toggle
that flips the shipping-default MUST re-run the gate before submit.
"""
from __future__ import annotations

import math
from typing import Optional

from core.db import get_db


# ---------------------------------------------------------------------------
# Gate constants — locked. Loosen only via signed-off code change; the CI
# formula below and the SAMPLE_SIZE minimum together define the safety
# floor. Do NOT env-flag these into runtime knobs.
# ---------------------------------------------------------------------------
MIN_ACCURACY = 0.99
MIN_SAMPLE_SIZE = 200
CI_Z = 1.959963984540054  # 95% CI (two-sided), std normal quantile


def wilson_lower_bound(matches: int, samples: int) -> float:
    """Wilson score interval lower bound (95%). Fails safe for n<1."""
    if samples < 1:
        return 0.0
    p_hat = matches / samples
    z = CI_Z
    denom = 1 + z * z / samples
    center = p_hat + z * z / (2 * samples)
    radius = z * math.sqrt(p_hat * (1 - p_hat) / samples + z * z / (4 * samples * samples))
    return (center - radius) / denom


async def compute_user_accuracy(user_id: str, *, window_days: Optional[int] = 30) -> dict:
    """Aggregate the user's `form_fill_telemetry` and return
    `{n_samples, matches, mismatches, accuracy_pct, ci95_lower, ci95_upper}`.
    `window_days=None` means all-time (used by the initial cold-start
    gate); 30-day rolling window is the default for dashboards."""
    db = get_db()
    q: dict = {"user_id": user_id}
    if window_days:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        q["sample_ts"] = {"$gte": cutoff}
    matches_total = 0
    fields_total = 0
    n = 0
    async for r in db.form_fill_telemetry.find(q, {"_id": 0, "field_count": 1, "field_matches": 1}):
        n += 1
        fc = int(r.get("field_count") or 0)
        fm = int(r.get("field_matches") or 0)
        if fc <= 0:
            continue
        fields_total += fc
        matches_total += min(fm, fc)
    accuracy = (matches_total / fields_total) if fields_total > 0 else 0.0
    ci_low = wilson_lower_bound(matches_total, fields_total) if fields_total > 0 else 0.0
    # Symmetric upper bound (Wilson is asymmetric — this is an approximation).
    if fields_total > 0:
        z = CI_Z
        p_hat = matches_total / fields_total
        denom = 1 + z * z / fields_total
        center = p_hat + z * z / (2 * fields_total)
        radius = z * math.sqrt(p_hat * (1 - p_hat) / fields_total
                                 + z * z / (4 * fields_total * fields_total))
        ci_upp = (center + radius) / denom
    else:
        ci_upp = 0.0
    return {
        "n_samples": n,
        "n_fields": fields_total,
        "matches": matches_total,
        "mismatches": max(fields_total - matches_total, 0),
        "accuracy_pct": round(accuracy * 100, 3),
        "ci95_lower_pct": round(ci_low * 100, 3),
        "ci95_upper_pct": round(ci_upp * 100, 3),
        "window_days": window_days,
    }


async def is_auto_submit_allowed(user_id: str) -> tuple[bool, str, dict]:
    """Return `(allowed, reason, metrics)`. `allowed=True` ONLY when
    all conditions hold:
       * User opted in (settings.autopilot_auto_submit_opt_in==True)
       * Global feature flag not force-disabled (env AUTOPILOT_AUTO_SUBMIT=off)
       * n_fields >= MIN_SAMPLE_SIZE (fields, not sessions — telemetry is per-field)
       * Wilson-95% lower bound >= MIN_ACCURACY

    Reason strings are stable:
      * "allowed"
      * "user_not_opted_in"
      * "shipped_disabled"                (env kill-switch)
      * "insufficient_sample"             (n_fields < MIN_SAMPLE_SIZE)
      * "accuracy_below_threshold"        (ci95_lower < MIN_ACCURACY)

    The UI can render each reason honestly ("Locked — needs {N-n} more
    fills to unlock" / "Locked — measured accuracy 97.2%, needs ≥99%").
    """
    import os
    db = get_db()

    # Env kill-switch — global override (e.g. incident response).
    if os.environ.get("AUTOPILOT_AUTO_SUBMIT", "").lower() == "off":
        return False, "shipped_disabled", {}

    # Per-user opt-in flag. Read from a settings collection; default
    # False so the SHIPPING DEFAULT is DISABLED per rails.
    settings_row = await db.user_settings.find_one({"user_id": user_id},
                                                       {"_id": 0}) or {}
    if not settings_row.get("autopilot_auto_submit_opt_in", False):
        return False, "user_not_opted_in", {}

    metrics = await compute_user_accuracy(user_id, window_days=None)
    if metrics["n_fields"] < MIN_SAMPLE_SIZE:
        return False, "insufficient_sample", metrics
    if metrics["ci95_lower_pct"] / 100.0 < MIN_ACCURACY:
        return False, "accuracy_below_threshold", metrics
    return True, "allowed", metrics
