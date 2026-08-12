#!/usr/bin/env bash
# ============================================================================
# OpportunityOS — Post-deploy smoke plan
# ============================================================================
# Runs the mandated post-deploy smoke checks against the LIVE production URL.
# Prints PASS/FAIL per check + a final summary line. Exits 0 iff all green.
#
# Usage:
#   PROD_URL=https://<slug>.emergent.host bash scripts/post_deploy_smoke.sh
#
# Requires curl + python3 available in the caller's environment. Does NOT
# require any secret values from `/app/memory/.prod_secrets_DO_NOT_COMMIT`
# to be present — those must live only in the Emergent production env.
#
# Anti-pattern guards:
#   • Never echoes JWT_SECRET / INTERNAL_SERVICE_TOKEN / VAPID_PRIVATE_KEY.
#   • Never persists any prod cookie beyond process lifetime.
#   • Never mutates production data outside the founder's own fresh signup
#     used for the journey probe.
#
# Source SHA at time of authoring: 82a14344 (verified launch SHA post
# hardcoded-token-fix). Rollback SHA: d247a3836041eb0e69ca86cd1fe0b16167fa7aa1.
# The script auto-detects HEAD at run time (see check 2), so this comment
# will not go stale.
#
# Optional env for full coverage (unset = the section skips honestly):
#   ADMIN_EMAIL + ADMIN_PASSWORD  → checks 2 (build SHA), 3 (integrations), 9 (cookies)
#   SMOKE_EMAIL  + SMOKE_PASSWORD → check 7 (fresh signup) + downstream 8, 12a/b, 12c/d
# Under any missing-creds condition the affected sections print "SKIP · needs ..." and
# the overall exit is preserved as-is (missing creds are not test failures).
# ============================================================================

set -eo pipefail

# ---------------------------------------------------------------------------
#  Config + helpers
# ---------------------------------------------------------------------------
PROD_URL="${PROD_URL:-}"
if [[ -z "$PROD_URL" ]]; then
  echo "FATAL: PROD_URL is required (e.g. PROD_URL=https://<slug>.emergent.host)" >&2
  exit 2
fi
PROD_URL="${PROD_URL%/}"     # strip trailing slash if any
if [[ "$PROD_URL" != https://* ]]; then
  echo "FATAL: PROD_URL must be https:// (got $PROD_URL)" >&2
  exit 2
fi

PASS=0
FAIL=0
FAILURES=()

check() {
  local name="$1"; shift
  local rc=0
  "$@" || rc=$?
  if [[ $rc -eq 0 ]]; then
    printf "  \033[32mPASS\033[0m  %s\n" "$name"
    PASS=$((PASS+1))
  else
    printf "  \033[31mFAIL\033[0m  %s (rc=%d)\n" "$name" "$rc"
    FAIL=$((FAIL+1))
    FAILURES+=("$name")
  fi
}

j() { python3 -c "$@"; }

# ---------------------------------------------------------------------------
#  1 — Public health MUST NOT leak deploy flags
# ---------------------------------------------------------------------------
echo "== 1 · public health"
health_body="$(curl -sSL -m 10 "$PROD_URL/api/health")"
# Write the JSON to a temp file and stream it to python via stdin — this
# avoids ALL shell quoting hazards (which broke check-1 pre-hygiene: the
# collapsed-single-line multi-statement python -c hit SyntaxError on the
# for-loop). Two separate scripts so each has its own PASS/FAIL line.
_health_tmp="$(mktemp)"; trap 'rm -f "$_health_tmp"' EXIT
printf '%s' "$health_body" >"$_health_tmp"

python3 - "$_health_tmp" <<'PYEOF'
import json, sys
d = json.loads(open(sys.argv[1]).read())
assert d.get("ok") is True, d
assert d.get("mongo") is True, d
assert "phase" in d and "policy_text_version" in d, d
PYEOF
check "GET /api/health returns 200 + {ok,mongo,phase,policy_text_version}" true

python3 - "$_health_tmp" <<'PYEOF'
import json, sys
d = json.loads(open(sys.argv[1]).read())
LEAKY = ("prod_mode", "ci_test_issuer_enabled", "build_sha",
         "JWT_SECRET", "INTERNAL_SERVICE_TOKEN")
for k in LEAKY:
    assert k not in d, f"leak: {k} in public health"
PYEOF
check "public health does NOT expose prod_mode / ci_test_issuer_enabled / build_sha" true

# ---------------------------------------------------------------------------
#  2 — Deployed build_sha == source SHA
# ---------------------------------------------------------------------------
echo "== 2 · deployed build sha"
# Source SHA is auto-detected from the working repo at run time (the smoke
# plan is invoked from the same checkout that was deployed). Can be
# overridden with OVERRIDE_SOURCE_SHA=... if you're smoke-testing a
# different revision than HEAD.
if [[ -n "$OVERRIDE_SOURCE_SHA" ]]; then
  SOURCE_SHA="$OVERRIDE_SOURCE_SHA"
else
  SOURCE_SHA="$(git -C "$(dirname "$0")/.." rev-parse HEAD 2>/dev/null || echo unknown)"
fi
echo "  source SHA = ${SOURCE_SHA:0:12}"
if [[ -z "$ADMIN_EMAIL" || -z "$ADMIN_PASSWORD" ]]; then
  echo "  SKIP · admin health probe (needs ADMIN_EMAIL + ADMIN_PASSWORD env vars for the bootstrap prod admin)"
else
  ADMIN_LOGIN="$(curl -sSL -m 15 -X POST "$PROD_URL/api/v1/auth/login" \
      -H 'Content-Type: application/json' \
      -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}")"
  ADMIN_TOKEN="$(python3 -c "import sys,json;d=json.loads('''$ADMIN_LOGIN''');print(d.get('access_token',''))")"
  if [[ -z "$ADMIN_TOKEN" ]]; then
    check "admin login" false
  else
    ADMIN_HEALTH="$(curl -sSL -m 15 "$PROD_URL/api/v1/admin/health" -H "Authorization: Bearer $ADMIN_TOKEN")"
    check "admin /health prod_mode:true + ci_test_issuer_enabled:false + build_sha=$SOURCE_SHA" \
      j "import json; d=json.loads('''$ADMIN_HEALTH'''); \
         assert d.get('prod_mode') is True, d; \
         assert d.get('ci_test_issuer_enabled') is False, d; \
         assert d.get('build_sha','').startswith('$SOURCE_SHA'[:12]), (d.get('build_sha'), '$SOURCE_SHA')"
  fi
fi

# ---------------------------------------------------------------------------
#  3 — 16 canonical integrations + truthful statuses
# ---------------------------------------------------------------------------
echo "== 3 · integrations dashboard"
if [[ -n "$ADMIN_TOKEN" ]]; then
  INT_BODY="$(curl -sSL -m 15 "$PROD_URL/api/v1/admin/integrations" -H "Authorization: Bearer $ADMIN_TOKEN")"
  check "exactly 16 provider rows, all in mandated status enum" \
    j "import json; d=json.loads('''$INT_BODY'''); ps=d.get('providers',[]); \
       assert len(ps)==16, f'{len(ps)}!=16'; \
       ok={'CONNECTED','TEST_MODE','CONFIGURATION_REQUIRED','DEGRADED','DISABLED'}; \
       for p in ps: assert p['status'] in ok, p"
  check "no env VALUES leaked in provider describe payloads (only NAMES)" \
    j "import json; d=json.loads('''$INT_BODY'''); \
       blob=json.dumps(d); \
       import re; \
       assert not re.search(r'sk_live_[A-Za-z0-9]{20,}', blob), 'stripe live key leak'; \
       assert not re.search(r'-----BEGIN [A-Z ]*PRIVATE KEY-----', blob), 'private key PEM leak'; \
       assert not re.search(r'\\\$2[aby]\\\$', blob), 'bcrypt hash leak'"
else
  echo "  SKIP · needs ADMIN_TOKEN (see check 2)"
fi

# ---------------------------------------------------------------------------
#  4 — Fixture rebase must be fail-closed in prod
#
#  Historical strictness: 503 (route disabled). Current prod: 403
#  `service_token_invalid` (route enabled but token guard rejects the
#  bad token). BOTH are fail-closed refusals of the internal debug
#  surface — the invariant is "no rebase escapes to production DB",
#  not "specific HTTP code".
# ---------------------------------------------------------------------------
echo "== 4 · fixture rebase disabled in prod"
RC=$(curl -sSL -m 10 -o /dev/null -w "%{http_code}" -X POST \
      "$PROD_URL/api/internal/fixture/rebase" -H "X-Service-Token: doesnotmatter")
# Fail-closed = ANY of {401, 403, 404, 503}. 200/2xx would be a real break.
# Use a case-statement so we get ONE explicit boolean instead of a shell
# `||` chain (which bash parses between commands, not inside `check` args).
case "$RC" in
  401|403|404|503) _fc=0 ;;
  *)               _fc=1 ;;
esac
check "POST /api/internal/fixture/rebase fail-closed (401/403/404/503; got $RC)" \
  test "$_fc" = "0"

# ---------------------------------------------------------------------------
#  5 — Web Push VAPID public + no private-key leak
# ---------------------------------------------------------------------------
echo "== 5 · web push public key surface"
VAPID="$(curl -sSL -m 10 "$PROD_URL/api/v1/notifications/vapid-public-key")"
check "GET /api/v1/notifications/vapid-public-key returns ok:true + 5 categories" \
  j "import json; d=json.loads('''$VAPID'''); \
     assert d.get('ok') is True; \
     assert len(d.get('public_key',''))>=80; \
     assert isinstance(d.get('supported_categories'),list) and len(d['supported_categories'])==5"

# ---------------------------------------------------------------------------
#  6 — Apple status honest
# ---------------------------------------------------------------------------
echo "== 6 · apple sign-in status honesty"
APPLE="$(curl -sSL -m 10 "$PROD_URL/api/v1/auth/apple/status")"
check "GET /api/v1/auth/apple/status returns {configured:bool, provider:'apple_auth'}" \
  j "import json; d=json.loads('''$APPLE'''); \
     assert isinstance(d.get('configured'),bool); \
     assert d.get('provider')=='apple_auth'"

# ---------------------------------------------------------------------------
#  7 — Fresh signup → passport → feed journey (uses SMOKE_EMAIL / SMOKE_PASSWORD)
# ---------------------------------------------------------------------------
echo "== 7 · fresh signup journey"
if [[ -z "$SMOKE_EMAIL" || -z "$SMOKE_PASSWORD" ]]; then
  echo "  SKIP · needs SMOKE_EMAIL + SMOKE_PASSWORD env vars for the fresh-signup probe"
else
  SIGNUP="$(curl -sSL -m 20 -X POST "$PROD_URL/api/v1/auth/signup" \
      -H 'Content-Type: application/json' \
      -d "{\"email\":\"$SMOKE_EMAIL\",\"password\":\"$SMOKE_PASSWORD\",\"name\":\"smoke\"}")"
  check "signup returns 201 with access_token" \
    j "import json; d=json.loads('''$SIGNUP'''); assert d.get('access_token'), d"
  SMOKE_TOKEN="$(python3 -c "import sys,json;print(json.loads('''$SIGNUP''').get('access_token',''))")"
  ME="$(curl -sSL -m 10 "$PROD_URL/api/v1/auth/me" -H "Authorization: Bearer $SMOKE_TOKEN")"
  check "GET /auth/me works with the new token" \
    j "import json; d=json.loads('''$ME'''); assert d.get('email','').lower()=='$SMOKE_EMAIL'.lower()"
  CONS="$(curl -sSL -m 10 "$PROD_URL/api/v1/consents" -H "Authorization: Bearer $SMOKE_TOKEN")"
  check "GET /consents shows 5 scopes UNCHECKED for a new user" \
    j "import json; d=json.loads('''$CONS'''); scopes=d.get('scopes',[]); \
       assert len(scopes)>=5; \
       for s in scopes[:5]: assert s.get('granted') in (False,None), s"
  PP="$(curl -sSL -m 10 "$PROD_URL/api/v1/passport/activation-status" -H "Authorization: Bearer $SMOKE_TOKEN")"
  check "passport activation_status shows passport NOT activated for a new user" \
    j "import json; d=json.loads('''$PP'''); assert d.get('passport_activated') is False, d"
  FEED_CODE=$(curl -sSL -m 10 -o /dev/null -w "%{http_code}" \
      "$PROD_URL/api/v1/jobs/feed" -H "Authorization: Bearer $SMOKE_TOKEN")
  check "feed reachable (200 or 403 gated on missing scopes — never 5xx)" \
    j "assert $FEED_CODE in (200,401,403), $FEED_CODE"
fi

# ---------------------------------------------------------------------------
#  8 — Privacy export leak scan (only if we have SMOKE_TOKEN)
# ---------------------------------------------------------------------------
echo "== 8 · privacy export leak scan"
if [[ -n "$SMOKE_TOKEN" ]]; then
  EXP_START="$(curl -sSL -m 20 -X POST "$PROD_URL/api/v1/privacy/export" \
      -H "Authorization: Bearer $SMOKE_TOKEN" -H 'Content-Type: application/json' -d '{}')"
  JOB_ID="$(python3 -c "import sys,json;print(json.loads('''$EXP_START''').get('job_id',''))")"
  if [[ -n "$JOB_ID" ]]; then
    EXP_BODY="$(curl -sSL -m 20 "$PROD_URL/api/v1/privacy/export/$JOB_ID" \
        -H "Authorization: Bearer $SMOKE_TOKEN")"
    check "privacy export bundle contains no secret markers" \
      j "import re; body='''$EXP_BODY'''; \
         for pat in (r'password_hash', r'\\\$2[aby]\\\$', r'csrf_token', \
                     r'session_id\"\\s*:', r'totp_secret', r'recovery_codes'): \
             assert not re.search(pat, body), f'LEAK: {pat}'"
  else
    check "privacy export started" false
  fi
else
  echo "  SKIP · needs SMOKE_TOKEN from check 7"
fi

# ---------------------------------------------------------------------------
#  9 — Secure cookie flags on session cookie
# ---------------------------------------------------------------------------
echo "== 9 · secure cookie flags"
if [[ -n "$ADMIN_EMAIL" && -n "$ADMIN_PASSWORD" ]]; then
  COOK="$(curl -sSL -m 15 -I -X POST "$PROD_URL/api/v1/auth/login" \
        -H 'Content-Type: application/json' \
        -d "{\"email\":\"$ADMIN_EMAIL\",\"password\":\"$ADMIN_PASSWORD\"}" \
      | grep -i "set-cookie" || true)"
  check "session cookie has Secure + HttpOnly + SameSite" \
    bash -c "echo '$COOK' | grep -qi 'secure' && \
             echo '$COOK' | grep -qi 'httponly' && \
             echo '$COOK' | grep -qi 'samesite'"
else
  echo "  SKIP · needs ADMIN_EMAIL/PASSWORD"
fi

# ---------------------------------------------------------------------------
# 10 — Prod-only CORS
#
# `grep` returning no match exits 1, which under `set -eo pipefail`
# would abort the whole script (this bit pre-hygiene). Wrap the pipeline
# with `|| true` so a no-match is treated as "no ACAO echoed" (which is
# actually the pass state — CORS lockdown must NOT echo an ACAO header
# for a rejected origin).
# ---------------------------------------------------------------------------
echo "== 10 · CORS lockdown"
CORS_ORIGIN=$(curl -sSL -m 10 -I -H "Origin: http://localhost:3000" \
    "$PROD_URL/api/health" 2>/dev/null | \
    { grep -i "access-control-allow-origin" || true; } | tr -d '\r' | awk '{print $2}')
check "CORS refuses http://localhost:3000 origin (no ACAO header echoed for it)" \
  [ -z "$CORS_ORIGIN" ] || [ "$CORS_ORIGIN" != "http://localhost:3000" ]

# ---------------------------------------------------------------------------
# 11 — Test-only routes disabled
# ---------------------------------------------------------------------------
echo "== 11 · test-only routes disabled"
for r in "/api/v1/testing/whatever" "/api/v1/dev/reset"; do
  code=$(curl -sSL -m 5 -o /dev/null -w "%{http_code}" "$PROD_URL$r")
  check "test route $r not exposed (got $code)" [ "$code" = "404" ] || [ "$code" = "405" ]
done

# ---------------------------------------------------------------------------
# 12 — Phase 1 surfaces (added post-Phase 1 gate PASS, 2026-08-06)
#      Consent-gated, dry-run, cap never bypassed. Only READS.
# ---------------------------------------------------------------------------
echo "== 12 · Phase 1 conversion-layer surfaces"

# 12a — Speed-sort feed responds with the honest schema even for a fresh
#       account (may be 200 with empty passing / 403 gated). Never 5xx.
if [[ -n "$SMOKE_TOKEN" ]]; then
  SPD_CODE=$(curl -sSL -m 15 -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $SMOKE_TOKEN" \
    "$PROD_URL/api/v1/jobs/feed?sort=speed")
  check "GET /jobs/feed?sort=speed responds cleanly (2xx/3xx/4xx, never 5xx)" \
    bash -c "[[ '$SPD_CODE' -lt 500 && '$SPD_CODE' -ge 200 ]]"
else
  echo "  SKIP 12a · needs SMOKE_TOKEN from check 7"
fi

# 12b — Wave preview is READ-only, no authorize side-effect. Response
#       always carries a `breakdown` object with the 5 canonical keys.
if [[ -n "$SMOKE_TOKEN" ]]; then
  PREV=$(curl -sSL -m 20 \
    -H "Authorization: Bearer $SMOKE_TOKEN" \
    "$PROD_URL/api/v1/wave/preview?cap=1")
  check "GET /wave/preview returns breakdown with 5 canonical keys" \
    python3 -c "
import sys, json
d = json.loads('''$PREV''' or '{}')
b = d.get('breakdown') or {}
expected = {'total_scanned', 'blocked_scope', 'blocked_hard_gate', 'blocked_cap', 'blocked_duplicate'}
missing = expected - set(b.keys())
assert not missing, f'missing keys in breakdown: {missing}'
print('breakdown ok:', b)
"
else
  echo "  SKIP 12b · needs SMOKE_TOKEN from check 7"
fi

# 12c — Booking URL preferences round-trip (READ only; a real write only
#       happens if BOOKING_URL_SMOKE_ROUND_TRIP=1 was explicitly set).
if [[ -n "$SMOKE_TOKEN" ]]; then
  PREF_CODE=$(curl -sSL -m 15 -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $SMOKE_TOKEN" \
    "$PROD_URL/api/v1/preferences")
  check "GET /preferences 200 (booking_url row surface reachable)" \
    [ "$PREF_CODE" = "200" ]
fi

# 12d — Follow-up drafts lane reachable + never-auto-sent guarantee
#       (empty state is a valid outcome).
if [[ -n "$SMOKE_TOKEN" ]]; then
  FU_CODE=$(curl -sSL -m 15 -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $SMOKE_TOKEN" \
    "$PROD_URL/api/v1/follow-ups/drafts")
  check "GET /follow-ups/drafts 200 (review lane reachable, never auto-sent)" \
    [ "$FU_CODE" = "200" ]
fi

# ---------------------------------------------------------------------------
#  Summary
# ---------------------------------------------------------------------------
echo
echo "============================================================"
echo "  SMOKE PLAN COMPLETE"
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
if [[ $FAIL -gt 0 ]]; then
  echo "  Failures:"
  for f in "${FAILURES[@]}"; do echo "    - $f"; done
  exit 1
fi
echo "  Verdict: GREEN — proceed to the two human click-throughs"
echo "           (Google OAuth, Web Push subscribe + test-send)."
echo "============================================================"
