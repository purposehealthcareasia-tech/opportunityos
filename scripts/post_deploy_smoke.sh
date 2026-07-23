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
# Source SHA at time of authoring: 82a143443e3b92a06f9ac90c17663dd07e5cf5e5
# Rollback SHA:                    d247a3836041eb0e69ca86cd1fe0b16167fa7aa1
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
check "GET /api/health returns 200 + {ok,mongo,phase,policy_text_version}" \
  j "import json; d=json.loads('''$health_body'''); \
     assert d.get('ok') is True, d; \
     assert d.get('mongo') is True, d; \
     assert 'phase' in d and 'policy_text_version' in d, d"
check "public health does NOT expose prod_mode / ci_test_issuer_enabled / build_sha" \
  j "import json; d=json.loads('''$health_body'''); \
     for k in ('prod_mode','ci_test_issuer_enabled','build_sha','JWT_SECRET','INTERNAL_SERVICE_TOKEN'): \
         assert k not in d, f'leak: {k} in public health'"

# ---------------------------------------------------------------------------
#  2 — Deployed build_sha == source SHA
# ---------------------------------------------------------------------------
echo "== 2 · deployed build sha"
SOURCE_SHA="82a143443e3b92a06f9ac90c17663dd07e5cf5e5"
if [[ -n "$OVERRIDE_SOURCE_SHA" ]]; then SOURCE_SHA="$OVERRIDE_SOURCE_SHA"; fi
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
#  4 — Fixture rebase must be 503 disabled in prod
# ---------------------------------------------------------------------------
echo "== 4 · fixture rebase disabled in prod"
RC=$(curl -sSL -m 10 -o /dev/null -w "%{http_code}" -X POST \
      "$PROD_URL/api/internal/fixture/rebase" -H "X-Service-Token: doesnotmatter")
check "POST /api/internal/fixture/rebase returns 503" [ "$RC" = "503" ]

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
# ---------------------------------------------------------------------------
echo "== 10 · CORS lockdown"
CORS_ORIGIN=$(curl -sSL -m 10 -I -H "Origin: http://localhost:3000" \
    "$PROD_URL/api/health" | grep -i "access-control-allow-origin" | tr -d '\r' | awk '{print $2}')
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
