#!/usr/bin/env bash
# ============================================================================
#  OpportunityOS — Web Push real click-through checklist
#  Runs entirely in the founder's browser.
# ============================================================================
PROD_URL="${PROD_URL:-}"
if [[ -z "$PROD_URL" ]]; then
  echo "FATAL: PROD_URL is required" >&2; exit 2
fi
PROD_URL="${PROD_URL%/}"
cat <<EOF
============================================================
WEB PUSH REAL SUBSCRIBE + TEST-SEND (founder, real browser)
============================================================
Line 1: Log in on $PROD_URL, open Settings → Notifications →
        Enable notifications.
Line 2: Grant the browser permission prompt, then click Send test
        notification.
Line 3: Confirm an OS-level push actually arrives on your device
        (title + body + click routes back to the app).
============================================================
Post-click verification (I run this automatically):
  1. GET /api/v1/notifications/subscriptions → one active row for
     your user with your device's endpoint_tail.
  2. audit_logs grep for notifications.dispatched with sent:1 for
     your user.
  3. Flip the audit-report row status:
       push_notifications: HUMAN_VERIFICATION_REQUIRED → PRODUCTION_READY
============================================================
EOF
