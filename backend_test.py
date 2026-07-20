"""
OpportunityOS Phase 1 — Backend verification suite.

Runs against the preview base URL from frontend/.env, verifies the 13 review
checks the main agent requested, plus a concurrency sanity check.

Prints PASS/FAIL per numbered check with evidence.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from typing import Any

import httpx
from motor.motor_asyncio import AsyncIOMotorClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE = "https://af7cc636-8506-4548-af82-a1a50aae0158.preview.emergentagent.com"
API = f"{BASE}/api"
V1 = f"{API}/v1"

USER_ZERO = ("ujjwal@opportunityos.dev", "Passport!Test0")
ADMIN = ("admin@opportunityos.dev", "Admin!Console1")
SUPPORT = ("support@opportunityos.dev", "Support!Console1")

MONGO_URL = "mongodb://localhost:27017"
DB_NAME = "opportunityos"

RESULTS: list[tuple[str, bool, str]] = []


def _record(name: str, ok: bool, evidence: str) -> None:
    RESULTS.append((name, ok, evidence))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name} — {evidence}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _login(client: httpx.AsyncClient, email: str, password: str) -> dict:
    r = await client.post(f"{V1}/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
async def check_1_health(client: httpx.AsyncClient) -> None:
    r = await client.get(f"{API}/health")
    ok = r.status_code == 200 and r.json().get("mongo") is True
    _record("1. GET /api/health → 200 mongo:true", ok,
            f"status={r.status_code} body={r.text[:200]}")


async def check_2_openapi(client: httpx.AsyncClient) -> None:
    r = await client.get(f"{API}/openapi.json")
    if r.status_code != 200:
        _record("2. openapi reachable", False, f"status={r.status_code}")
        return
    spec = r.json()
    required = [
        "/api/v1/auth/signup", "/api/v1/auth/login", "/api/v1/auth/me",
        "/api/v1/consents", "/api/v1/consents/scopes",
        "/api/v1/users/me", "/api/v1/users/me/claims", "/api/v1/users/me/change-password",
        "/api/v1/users/{user_id}",
        "/api/v1/admin/feature-flags", "/api/v1/admin/health",
        "/api/v1/passport/ping", "/api/v1/meta/policy",
    ]
    missing = [p for p in required if p not in spec.get("paths", {})]
    ok = not missing and isinstance(spec.get("openapi"), str)
    _record("2. openapi has all required paths", ok,
            f"missing={missing} openapi_version={spec.get('openapi')}")


async def check_3_signup_happy(client: httpx.AsyncClient) -> dict:
    email = f"qa-{uuid.uuid4().hex[:10]}@opportunityos.dev"
    body = {
        "email": email,
        "password": "TestPass!123",
        "name": "QA Applicant",
        "consents": {
            "process_career_data": True,
            "discover_jobs": False,
            "generate_materials": False,
            "track_applications": False,
            "email_me": False,
        },
        "policy_text_version": "1.0",
    }
    r = await client.post(f"{V1}/auth/signup", json=body)
    ok = r.status_code == 201 and "access_token" in r.json() and r.json()["user"]["role"] == "user"
    _record("3. Signup happy path (only required consent)", ok,
            f"status={r.status_code} keys={list(r.json().keys()) if r.status_code<400 else r.text[:200]}")
    return r.json() if r.status_code == 201 else {}


async def check_4_signup_missing_required(client: httpx.AsyncClient) -> None:
    email = f"qa-{uuid.uuid4().hex[:10]}@opportunityos.dev"
    body = {
        "email": email,
        "password": "TestPass!123",
        "name": "QA Reject",
        "consents": {
            "process_career_data": False,
            "discover_jobs": True,
            "generate_materials": False,
            "track_applications": False,
            "email_me": False,
        },
        "policy_text_version": "1.0",
    }
    r = await client.post(f"{V1}/auth/signup", json=body)
    ok = False
    detail = None
    if r.status_code == 400:
        detail = r.json().get("detail", {})
        ok = (isinstance(detail, dict)
              and detail.get("error") == "required_consent_missing"
              and detail.get("scope") == "process_career_data")
    _record("4. Signup rejects when required consent missing", ok,
            f"status={r.status_code} detail={detail}")


async def check_5_login_all(client: httpx.AsyncClient) -> dict[str, dict]:
    tokens: dict[str, dict] = {}
    for label, (email, pw), expected_role in [
        ("user_zero", USER_ZERO, "user"),
        ("admin", ADMIN, "admin"),
        ("support", SUPPORT, "support"),
    ]:
        r = await client.post(f"{V1}/auth/login", json={"email": email, "password": pw})
        if r.status_code == 200:
            data = r.json()
            role = data["user"]["role"]
            ok = "access_token" in data and role == expected_role
            _record(f"5. Login {label} role={expected_role}", ok,
                    f"status=200 got_role={role}")
            if ok:
                tokens[label] = {"token": data["access_token"], "user_id": data["user"]["id"]}
        else:
            _record(f"5. Login {label} role={expected_role}", False, f"status={r.status_code} body={r.text[:200]}")
    return tokens


async def check_6_me(client: httpx.AsyncClient, tokens: dict[str, dict]) -> None:
    for label, expected_role in [("user_zero", "user"), ("admin", "admin"), ("support", "support")]:
        if label not in tokens:
            _record(f"6. /auth/me {label}", False, "no token")
            continue
        r = await client.get(f"{V1}/auth/me", headers=_bearer(tokens[label]["token"]))
        ok = r.status_code == 200 and r.json().get("role") == expected_role
        _record(f"6. GET /auth/me role={expected_role}", ok,
                f"status={r.status_code} role={r.json().get('role') if r.status_code<400 else '-'}")


async def check_7_consent_gate(client: httpx.AsyncClient, tokens: dict[str, dict]) -> None:
    if "user_zero" not in tokens:
        _record("7. Consent gate", False, "no user_zero token")
        return
    hdr = _bearer(tokens["user_zero"]["token"])

    # a. ping should be 200 (baseline)
    r = await client.get(f"{V1}/passport/ping", headers=hdr)
    _record("7a. ping BEFORE revoke → 200", r.status_code == 200, f"status={r.status_code}")

    # b. revoke process_career_data
    r = await client.post(f"{V1}/consents", headers=hdr, json={
        "scope": "process_career_data", "granted": False, "policy_text_version": "1.0",
    })
    _record("7b. POST revoke → 201", r.status_code == 201, f"status={r.status_code} body={r.text[:200]}")

    # c. ping should now 403 with machine-readable detail
    r = await client.get(f"{V1}/passport/ping", headers=hdr)
    ok = False
    detail = None
    if r.status_code == 403:
        detail = r.json().get("detail", {})
        ok = (detail.get("error") == "consent_required"
              and detail.get("scope") == "process_career_data"
              and detail.get("grant_url") == "/api/v1/consents")
    _record("7c. ping AFTER revoke → 403 consent_required", ok,
            f"status={r.status_code} detail={detail}")

    # d. re-grant
    r = await client.post(f"{V1}/consents", headers=hdr, json={
        "scope": "process_career_data", "granted": True, "policy_text_version": "1.0",
    })
    _record("7d. POST re-grant → 201", r.status_code == 201, f"status={r.status_code}")

    # e. ping should be 200 again
    r = await client.get(f"{V1}/passport/ping", headers=hdr)
    _record("7e. ping AFTER re-grant → 200", r.status_code == 200, f"status={r.status_code}")


async def check_7f_ledger(mongo_db, user_zero_id: str) -> None:
    count = await mongo_db.consent_records.count_documents(
        {"user_id": user_zero_id, "scope": "process_career_data"}
    )
    _record("7f. consent_records ≥3 rows for User Zero / process_career_data",
            count >= 3, f"rows={count}")


async def check_8_idempotency(client: httpx.AsyncClient, tokens: dict[str, dict], mongo_db) -> None:
    if "user_zero" not in tokens:
        _record("8. Idempotency", False, "no user_zero token"); return
    hdr = _bearer(tokens["user_zero"]["token"])
    user_id = tokens["user_zero"]["user_id"]

    idem_key = f"qa-idem-{uuid.uuid4().hex}"
    body = {"scope": "discover_jobs", "granted": True, "policy_text_version": "1.0"}

    # count rows/audits before
    before_consent = await mongo_db.consent_records.count_documents(
        {"user_id": user_id, "scope": "discover_jobs"}
    )
    before_audit = await mongo_db.audit_logs.count_documents(
        {"actor": user_id, "action": {"$in": ["consent.grant", "consent.revoke"]},
         "meta.scope": "discover_jobs"}
    )

    r1 = await client.post(f"{V1}/consents", headers={**hdr, "Idempotency-Key": idem_key}, json=body)
    r2 = await client.post(f"{V1}/consents", headers={**hdr, "Idempotency-Key": idem_key}, json=body)

    byte_identical = r1.content == r2.content
    replay_header = r2.headers.get("X-Idempotent-Replay") == "true"
    _record("8a. Same Idempotency-Key: byte-identical + X-Idempotent-Replay:true",
            r1.status_code == 201 and r2.status_code == 201 and byte_identical and replay_header,
            f"s1={r1.status_code} s2={r2.status_code} bytes_eq={byte_identical} replay_hdr={r2.headers.get('X-Idempotent-Replay')}")

    after_consent = await mongo_db.consent_records.count_documents(
        {"user_id": user_id, "scope": "discover_jobs"}
    )
    after_audit = await mongo_db.audit_logs.count_documents(
        {"actor": user_id, "action": {"$in": ["consent.grant", "consent.revoke"]},
         "meta.scope": "discover_jobs"}
    )
    _record("8b. Only ONE consent row + ONE audit row appended per idempotent pair",
            (after_consent - before_consent == 1) and (after_audit - before_audit == 1),
            f"consent Δ={after_consent - before_consent} audit Δ={after_audit - before_audit}")

    # different key, same body → new side effect
    idem_key2 = f"qa-idem-{uuid.uuid4().hex}"
    r3 = await client.post(f"{V1}/consents", headers={**hdr, "Idempotency-Key": idem_key2}, json=body)
    after2_consent = await mongo_db.consent_records.count_documents(
        {"user_id": user_id, "scope": "discover_jobs"}
    )
    after2_audit = await mongo_db.audit_logs.count_documents(
        {"actor": user_id, "action": {"$in": ["consent.grant", "consent.revoke"]},
         "meta.scope": "discover_jobs"}
    )
    _record("8c. Different Idempotency-Key + same body → new row + audit",
            r3.status_code == 201 and (after2_consent - after_consent == 1) and (after2_audit - after_audit == 1),
            f"status={r3.status_code} consent Δ={after2_consent - after_consent} audit Δ={after2_audit - after_audit}")


async def check_9_sealed(client: httpx.AsyncClient, tokens: dict[str, dict]) -> None:
    if "user_zero" not in tokens:
        _record("9. Sealed", False, "no user_zero token"); return
    uz_id = tokens["user_zero"]["user_id"]

    # a. Owner sees the real value
    r = await client.get(f"{V1}/users/me/claims", headers=_bearer(tokens["user_zero"]["token"]))
    claims = r.json().get("claims", []) if r.status_code == 200 else []
    wa = next((c for c in claims if c.get("type") == "work_auth"), None)
    ok = (wa is not None and wa.get("sensitivity") == "sealed"
          and isinstance(wa.get("value"), dict) and wa["value"].get("status") == "unspecified"
          and "_sealed" not in wa)
    _record("9a. Owner sees real work_auth value (no _sealed flag)", ok,
            f"status={r.status_code} work_auth={wa if wa else 'missing'}")

    # b. Admin sees masked
    r = await client.get(f"{V1}/users/{uz_id}", headers=_bearer(tokens["admin"]["token"]))
    claims = r.json().get("claims", []) if r.status_code == 200 else []
    wa = next((c for c in claims if c.get("type") == "work_auth"), None)
    ok = (wa is not None and wa.get("value") == "•••• (sealed)" and wa.get("_sealed") is True)
    _record("9b. Admin sees work_auth as '•••• (sealed)' with _sealed:true", ok,
            f"status={r.status_code} wa_value={wa.get('value') if wa else '-'} _sealed={wa.get('_sealed') if wa else '-'}")

    # c. Support sees masked
    r = await client.get(f"{V1}/users/{uz_id}", headers=_bearer(tokens["support"]["token"]))
    claims = r.json().get("claims", []) if r.status_code == 200 else []
    wa = next((c for c in claims if c.get("type") == "work_auth"), None)
    ok = (wa is not None and wa.get("value") == "•••• (sealed)" and wa.get("_sealed") is True)
    _record("9c. Support sees identical masking", ok,
            f"status={r.status_code} wa_value={wa.get('value') if wa else '-'} _sealed={wa.get('_sealed') if wa else '-'}")


async def check_10_role_gating(client: httpx.AsyncClient, tokens: dict[str, dict]) -> None:
    # user → 403
    r = await client.get(f"{V1}/admin/feature-flags", headers=_bearer(tokens["user_zero"]["token"]))
    _record("10a. User → /admin/feature-flags 403", r.status_code == 403, f"status={r.status_code}")

    expected_flags = {"feed_enabled": True, "ai_generation_enabled": False,
                      "application_tracker_enabled": False, "billing_enabled": False}

    for label in ("admin", "support"):
        r = await client.get(f"{V1}/admin/feature-flags", headers=_bearer(tokens[label]["token"]))
        if r.status_code != 200:
            _record(f"10. {label} → /admin/feature-flags 200", False, f"status={r.status_code}")
            continue
        flags = {f["key"]: f["value"] for f in r.json().get("flags", [])}
        missing = [k for k, v in expected_flags.items() if flags.get(k) != v]
        _record(f"10. {label} sees expected 4 feature flag values", not missing,
                f"got={flags} missing_or_wrong={missing}")


async def check_11_seed_integrity(mongo_db, user_zero_id: str) -> None:
    # a. taxonomy count == 13
    tax_count = await mongo_db.taxonomy.count_documents({})
    expected_families = {
        "vehicle systems", "battery systems/test", "simulation (MIL/SIL/HIL)",
        "controls", "vehicle dynamics", "thermal/energy", "mechanical design",
        "test engineer", "robotics", "applications engineer", "systems engineer",
        "manufacturing/process", "equipment engineer",
    }
    fams = {t["family"] async for t in mongo_db.taxonomy.find({}, {"family": 1})}
    _record("11a. taxonomy count==13 & all families present",
            tax_count == 13 and expected_families.issubset(fams),
            f"count={tax_count} missing={expected_families - fams}")

    # b. companies
    company_count = await mongo_db.companies.count_documents({})
    sampleco = await mongo_db.companies.find_one({"domain": "sampleco.demo"})
    real_verified = await mongo_db.companies.count_documents({"verified_domain": True})
    real_green_lane = await mongo_db.companies.count_documents({"verified_domain": True, "green_lane": True})
    ok = (company_count == 26
          and sampleco is not None and sampleco.get("verified_domain") is False
          and real_verified == 25
          and real_green_lane == 0)
    _record("11b. companies==26 (25 real + SampleCo), SampleCo verified_domain:false, real green_lane:false", ok,
            f"count={company_count} sampleco_verified={sampleco.get('verified_domain') if sampleco else None} real_verified={real_verified} real_green_lane={real_green_lane}")

    # c. sample jobs
    sample_jobs = await mongo_db.jobs.count_documents({"is_sample": True})
    keys = [j["canonical_key"] async for j in mongo_db.jobs.find({"is_sample": True}, {"canonical_key": 1})]
    key_pattern_ok = all(k.startswith("sampleco.demo::sample-") and len(k) == len("sampleco.demo::sample-") + 2 for k in keys)
    _record("11c. sample jobs==15 with canonical_key sampleco.demo::sample-NN unique",
            sample_jobs == 15 and key_pattern_ok and len(set(keys)) == len(keys),
            f"count={sample_jobs} unique={len(set(keys))} key_pattern_ok={key_pattern_ok}")

    # d. User Zero claims
    claim_count = await mongo_db.claims.count_documents({"user_id": user_zero_id})
    not_approved = await mongo_db.claims.count_documents({"user_id": user_zero_id, "user_approved": False})
    verified_zero = await mongo_db.claims.count_documents({"user_id": user_zero_id, "verification.level": 0})
    work_auth = await mongo_db.claims.find_one({"user_id": user_zero_id, "type": "work_auth"})
    ok = (claim_count == 16
          and not_approved == 16
          and verified_zero == 16
          and work_auth is not None
          and work_auth.get("sensitivity") == "sealed")
    _record("11d. User Zero has 16 claims all unapproved, level=0, work_auth sealed", ok,
            f"total={claim_count} not_approved={not_approved} level0={verified_zero} work_auth_sensitivity={work_auth.get('sensitivity') if work_auth else 'missing'}")

    # e. feature_flags exact 4 keys
    ff_keys = {f["key"] async for f in mongo_db.feature_flags.find({}, {"key": 1})}
    expected_keys = {"feed_enabled", "ai_generation_enabled",
                     "application_tracker_enabled", "billing_enabled"}
    _record("11e. feature_flags has exactly the 4 seeded keys",
            ff_keys == expected_keys,
            f"got={sorted(ff_keys)}")

    # f. admin_users
    admin_user = await mongo_db.users.find_one({"email": "admin@opportunityos.dev"})
    support_user = await mongo_db.users.find_one({"email": "support@opportunityos.dev"})
    admin_row = await mongo_db.admin_users.find_one({"user_id": admin_user["id"]}) if admin_user else None
    support_row = await mongo_db.admin_users.find_one({"user_id": support_user["id"]}) if support_user else None
    ok = (admin_row and admin_row.get("role") == "admin"
          and support_row and support_row.get("role") == "support")
    _record("11f. admin_users: admin@ role=admin, support@ role=support", bool(ok),
            f"admin_role={admin_row.get('role') if admin_row else None} support_role={support_row.get('role') if support_row else None}")


async def check_12_users_domain(client: httpx.AsyncClient, tokens: dict[str, dict], mongo_db) -> None:
    hdr = _bearer(tokens["user_zero"]["token"])
    uz_id = tokens["user_zero"]["user_id"]

    # a. PATCH name
    original = (await client.get(f"{V1}/users/me", headers=hdr)).json()
    original_name = original.get("name")

    audit_before = await mongo_db.audit_logs.count_documents(
        {"actor": uz_id, "action": "user.profile_update"}
    )
    new_name = f"{original_name} QA"
    r = await client.patch(f"{V1}/users/me", headers=hdr, json={"name": new_name})
    audit_after = await mongo_db.audit_logs.count_documents(
        {"actor": uz_id, "action": "user.profile_update"}
    )
    ok = (r.status_code == 200 and r.json().get("name") == new_name
          and audit_after - audit_before == 1)
    _record("12a. PATCH /users/me updates name + writes user.profile_update audit",
            ok, f"status={r.status_code} name={r.json().get('name')} audit Δ={audit_after - audit_before}")

    # restore
    await client.patch(f"{V1}/users/me", headers=hdr, json={"name": original_name})

    # b. change-password
    new_pw = "NewPass!Rotation1"
    # wrong current password → 400 current_password_incorrect
    r = await client.post(f"{V1}/users/me/change-password", headers=hdr, json={
        "current_password": "wrongwrong9!", "new_password": new_pw,
    })
    ok = r.status_code == 400 and r.json().get("detail") == "current_password_incorrect"
    _record("12b1. change-password with wrong current → 400 current_password_incorrect", ok,
            f"status={r.status_code} body={r.text[:200]}")

    # correct current → 204
    r = await client.post(f"{V1}/users/me/change-password", headers=hdr, json={
        "current_password": USER_ZERO[1], "new_password": new_pw,
    })
    _record("12b2. change-password with correct current → 204", r.status_code == 204,
            f"status={r.status_code}")

    # login with new password
    r = await client.post(f"{V1}/auth/login", json={"email": USER_ZERO[0], "password": new_pw})
    _record("12b3. login with NEW password → 200", r.status_code == 200,
            f"status={r.status_code}")

    # revert password back to seed
    if r.status_code == 200:
        new_token = r.json()["access_token"]
        rev = await client.post(f"{V1}/users/me/change-password",
                                headers=_bearer(new_token),
                                json={"current_password": new_pw, "new_password": USER_ZERO[1]})
        _record("12b4. revert User Zero password back to seed (204)",
                rev.status_code == 204, f"status={rev.status_code}")

        # confirm we can login with the seed password again
        r = await client.post(f"{V1}/auth/login", json={"email": USER_ZERO[0], "password": USER_ZERO[1]})
        _record("12b5. login with seed password after revert → 200",
                r.status_code == 200, f"status={r.status_code}")


async def check_13_concurrent_idempotency(client: httpx.AsyncClient, tokens: dict[str, dict], mongo_db) -> None:
    hdr = _bearer(tokens["user_zero"]["token"])
    user_id = tokens["user_zero"]["user_id"]
    scope = "email_me"
    idem_key = f"qa-concurrent-{uuid.uuid4().hex}"
    body = {"scope": scope, "granted": True, "policy_text_version": "1.0"}

    before = await mongo_db.consent_records.count_documents({"user_id": user_id, "scope": scope})

    async def fire():
        return await client.post(f"{V1}/consents",
                                 headers={**hdr, "Idempotency-Key": idem_key},
                                 json=body)

    r1, r2 = await asyncio.gather(fire(), fire())
    after = await mongo_db.consent_records.count_documents({"user_id": user_id, "scope": scope})
    delta = after - before
    ok = (r1.status_code == 201 and r2.status_code == 201 and delta == 1)
    _record("13. Concurrent idempotent POST → exactly ONE row appended", ok,
            f"s1={r1.status_code} s2={r2.status_code} rows_delta={delta}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> int:
    mongo_client = AsyncIOMotorClient(MONGO_URL, uuidRepresentation="standard")
    mongo_db = mongo_client[DB_NAME]

    # Resolve User Zero id from DB (stable across runs)
    uz = await mongo_db.users.find_one({"email": "ujjwal@opportunityos.dev"})
    if not uz:
        print("FATAL: User Zero not seeded"); return 1
    user_zero_id = uz["id"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        await check_1_health(client)
        await check_2_openapi(client)
        await check_3_signup_happy(client)
        await check_4_signup_missing_required(client)
        tokens = await check_5_login_all(client)
        if "user_zero" not in tokens:
            print("FATAL: could not login User Zero — aborting remaining checks"); return 1
        await check_6_me(client, tokens)
        await check_7_consent_gate(client, tokens)
        await check_7f_ledger(mongo_db, user_zero_id)
        await check_8_idempotency(client, tokens, mongo_db)
        await check_9_sealed(client, tokens)
        await check_10_role_gating(client, tokens)
        await check_11_seed_integrity(mongo_db, user_zero_id)
        await check_12_users_domain(client, tokens, mongo_db)
        await check_13_concurrent_idempotency(client, tokens, mongo_db)

    print("\n\n===== SUMMARY =====")
    fails = [r for r in RESULTS if not r[1]]
    passes = [r for r in RESULTS if r[1]]
    print(f"Total: {len(RESULTS)} — PASS: {len(passes)} — FAIL: {len(fails)}")
    if fails:
        print("\nFailures:")
        for name, _, ev in fails:
            print(f"  - {name}\n      {ev}")
    return 0 if not fails else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
