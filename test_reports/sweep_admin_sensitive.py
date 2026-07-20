"""Iteration 9 sweep — check ALL admin endpoints for credential leakage
and capture the sanitized user-detail body verbatim."""
from __future__ import annotations
import json
import os
import re
import sys
import requests

BASE = "https://lynk-preview-2.preview.emergentagent.com"

def _login(email, pw):
    r = requests.post(f"{BASE}/api/v1/auth/login", json={"email": email, "password": pw})
    r.raise_for_status()
    return r.json()["access_token"]


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


BCRYPT_RE = re.compile(r"\$2[abyxy]\$")
FORBIDDEN_KEYS = ("password_hash", "totp_secret", "recovery_codes")


def _scan(label, body_text):
    """Return list of leak descriptions found in body_text."""
    leaks = []
    for k in FORBIDDEN_KEYS:
        if k in body_text:
            leaks.append(f"{label}: contains substring `{k}`")
    if BCRYPT_RE.search(body_text):
        leaks.append(f"{label}: contains bcrypt marker (\\$2[abxy]\\$)")
    return leaks


def main():
    admin_tok = _login("admin@opportunityos.dev", "Admin!Console1")
    support_tok = _login("support@opportunityos.dev", "Support!Console1")

    print("=" * 78)
    print("SWEEP — admin endpoints (admin bearer)")
    print("=" * 78)

    endpoints = [
        "/api/v1/admin/users",
        "/api/v1/admin/subscriptions",
        "/api/v1/admin/manual-queue",
        "/api/v1/admin/flags",
        "/api/v1/admin/support-tickets",
        "/api/v1/admin/health",
        "/api/v1/admin/observability/events",
        "/api/v1/admin/observability/errors",
    ]

    all_leaks = []
    for path in endpoints:
        r = requests.get(f"{BASE}{path}", headers=_hdr(admin_tok))
        try:
            body_text = r.text
        except Exception:
            body_text = ""
        status = r.status_code
        leaks = _scan(path, body_text)
        all_leaks.extend(leaks)
        print(f"  {path:55} → {status}  leaks: {leaks or 'clean'}")

    # Now fetch fixture user detail with admin and support
    r0 = requests.get(f"{BASE}/api/v1/admin/users?q=fixture", headers=_hdr(admin_tok))
    fixture_uid = r0.json()["users"][0]["id"]
    print(f"\nFixture uid: {fixture_uid}")

    for label, tok in (("admin", admin_tok), ("support", support_tok)):
        r = requests.get(f"{BASE}/api/v1/admin/users/{fixture_uid}", headers=_hdr(tok))
        assert r.status_code == 200, f"{label}: {r.status_code} {r.text}"
        body_text = r.text
        leaks = _scan(f"/admin/users/{{id}} ({label})", body_text)
        u = r.json()["user"]
        for k in FORBIDDEN_KEYS + ("password",):
            if k in u:
                all_leaks.append(f"{label}: user.{k} present")
        all_leaks.extend(leaks)
        print(f"  /admin/users/{{fixture}} ({label}) → 200  user keys={sorted(u.keys())}")
        print(f"    leaks: {leaks or 'clean'}")

        # Save admin-body verbatim for artifact
        if label == "admin":
            with open("/app/test_reports/p9-admin-user-detail-body.json", "w") as fh:
                json.dump(r.json(), fh, indent=2, default=str, sort_keys=True)
            print("    → wrote /app/test_reports/p9-admin-user-detail-body.json")

    # Also confirm no unmask/reveal/decrypt strings appear
    r = requests.get(f"{BASE}/api/v1/admin/users/{fixture_uid}", headers=_hdr(admin_tok))
    body_text = r.text
    for kw in ("unmask", "reveal", "decrypt"):
        if kw in body_text.lower():
            all_leaks.append(f"response contains '{kw}' keyword")

    print("\n" + "=" * 78)
    if all_leaks:
        print(f"FAIL — {len(all_leaks)} leak(s) detected:")
        for l in all_leaks:
            print(f"  - {l}")
        sys.exit(1)
    else:
        print("PASS — no credential leaks detected across all admin endpoints.")


if __name__ == "__main__":
    main()
