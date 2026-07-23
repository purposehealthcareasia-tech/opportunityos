#!/usr/bin/env bash
# ============================================================================
#  OpportunityOS — Google OAuth real click-through checklist
#  Runs entirely in the founder's browser. This script is a HELPER that
#  prints the exact 3 lines to relay and the exact server-side verification
#  I (the agent) will run automatically once you click "done".
# ============================================================================
PROD_URL="${PROD_URL:-}"
if [[ -z "$PROD_URL" ]]; then
  echo "FATAL: PROD_URL is required" >&2; exit 2
fi
PROD_URL="${PROD_URL%/}"
cat <<EOF
============================================================
GOOGLE OAUTH REAL CLICK-THROUGH (founder, real browser)
============================================================
Line 1: Open $PROD_URL/login → click Continue with Google.
Line 2: Pick a real Google account, grant the five consent scopes on
        the callback screen.
Line 3: Confirm you land on /passport with a logged-in session.
============================================================
Post-click verification (I run this automatically):
  1. audit_logs grep for auth.google_completed with your new user_id
     (via /api/v1/admin/audit-logs?event=auth.google_completed).
  2. GET /api/v1/auth/me with your new session cookie → confirm email
     matches the Google account you used.
  3. Flip the audit-report row status:
       google_auth: HUMAN_VERIFICATION_REQUIRED → PRODUCTION_READY
============================================================
EOF
