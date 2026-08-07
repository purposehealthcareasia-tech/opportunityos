"""Phase 4 tests — Eligibility explain + Ghosting evidence + Standards page."""
from __future__ import annotations
import hashlib
import hmac
import json
import pytest


# ----------------------------------------------------------------------
# Eligibility explain
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_eligibility_explain_lists_all_public_data_unknowns(monkeypatch):
    """The `unknown` list must enumerate EVERY public dataset the engine
    deliberately does NOT join with the user's profile. Locks the
    honesty invariant — a future refactor that quietly starts inferring
    a signal from a public dataset must FAIL this test unless the
    explain-list is updated."""
    from domains.eligibility import explain

    class _Coll:
        async def find_one(self, *_a, **_kw):
            return {"user_id": "u", "status": "ead_opt",
                    "opt_end": "2027-12-31", "earliest_start": "2026-03-01",
                    "derived_flags": {"itar_excluded": True,
                                       "e_verify_need": True,
                                       "sponsorship_need": True}}
    class _DB:
        eligibility_profiles = _Coll()
    monkeypatch.setattr(explain, "get_db", lambda: _DB())

    r = await explain.eligibility_explain(user={"id": "u"})
    # Fix 4 shape: each datum in `known` is now a labelled dict.
    assert r["known"]["status"]["value"] == "ead_opt"
    assert r["known"]["derived_flags"]["itar_excluded"]["value"] is True
    # Anti-regression: MUST enumerate at least these public-data unknowns.
    unknown_keys = {u["key"] for u in r["unknown"]}
    for required in (
        "us_person_status_source_of_truth",
        "e_verify_participation_of_target_employer",
        "employer_itar_registration",
        "specific_visa_class_current_priority_date",
        "employer_sponsorship_recent_history",
    ):
        assert required in unknown_keys, (required, unknown_keys)
    # Every unknown entry must carry a `why` — the honesty rail.
    for u in r["unknown"]:
        assert u.get("why"), u


@pytest.mark.asyncio
async def test_eligibility_explain_no_profile_is_honest(monkeypatch):
    """If no profile exists, `known.status` MUST be None and a
    plain-language note MUST explain — never a fabricated default."""
    from domains.eligibility import explain

    class _Coll:
        async def find_one(self, *_a, **_kw): return None
    class _DB:
        eligibility_profiles = _Coll()
    monkeypatch.setattr(explain, "get_db", lambda: _DB())

    r = await explain.eligibility_explain(user={"id": "u"})
    assert r["known"]["status"] is None
    assert "No eligibility profile" in r["known"]["note"]


# ----------------------------------------------------------------------
# Ghosting evidence export
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ghosting_signature_verifies_and_is_hmac_sha256(monkeypatch):
    """The signature MUST be an HMAC-SHA256 of the canonical
    serialization of the manifest body. Re-computing on the client
    must match exactly."""
    from domains.exports import ghosting

    class _Cursor:
        def __init__(self, docs): self._docs = list(docs)
        def __aiter__(self):
            async def gen():
                for d in self._docs: yield d
            return gen()

    class _AppsColl:
        def find(self, *_a, **_kw): return _Cursor([])
    class _OutColl:
        async def count_documents(self, *_a, **_kw): return 0
    class _DB:
        applications = _AppsColl()
        outcomes = _OutColl()
    monkeypatch.setattr(ghosting, "get_db", lambda: _DB())
    # Lock the signing key so the assertion is deterministic.
    monkeypatch.setenv("EVIDENCE_SIGNING_KEY", "unit-test-key-16b")

    r = await ghosting.ghosting_evidence(format="json", user={"id": "u-42"})
    body = r["manifest"]
    sig = r["signature"]
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"),
                             default=str).encode()
    expected = hmac.new(b"unit-test-key-16b", canonical,
                          hashlib.sha256).hexdigest()
    assert sig == expected
    assert len(sig) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_ghosting_only_flags_zero_response_after_threshold(monkeypatch):
    """An application older than the threshold with a `response` outcome
    MUST NOT appear in the ghosted list. Locks the "not-ghosted-if-
    responded" invariant."""
    from datetime import datetime, timedelta, timezone
    from domains.exports import ghosting

    old_created = datetime.now(timezone.utc) - timedelta(days=30)
    recent_created = datetime.now(timezone.utc) - timedelta(days=3)

    apps = [
        {"id": "a-old-ghosted", "user_id": "u", "state": "submitted",
          "created_at": old_created, "job_id": "j1", "employer": "E1"},
        {"id": "a-old-responded", "user_id": "u", "state": "response",
          "created_at": old_created, "job_id": "j2", "employer": "E2"},
        {"id": "a-recent", "user_id": "u", "state": "submitted",
          "created_at": recent_created, "job_id": "j3", "employer": "E3"},
    ]
    class _Cursor:
        def __init__(self, docs): self._docs = list(docs)
        def __aiter__(self):
            async def gen():
                for d in self._docs: yield d
            return gen()
    class _AppsColl:
        def find(self, q, *_a, **_kw):
            # Simulate the cutoff filter.
            cutoff = q.get("created_at", {}).get("$lt")
            state_not = q.get("state", {}).get("$ne")
            out = [d for d in apps
                   if (cutoff is None or d["created_at"] < cutoff)
                   and (state_not is None or d.get("state") != state_not)]
            return _Cursor(out)
    class _OutColl:
        async def count_documents(self, q, *_a, **_kw):
            # Only a-old-responded has a non-viewed outcome (response).
            if q.get("application_id") == "a-old-responded":
                return 1
            return 0
    class _DB:
        applications = _AppsColl()
        outcomes = _OutColl()
    monkeypatch.setattr(ghosting, "get_db", lambda: _DB())

    r = await ghosting.ghosting_evidence(format="json", user={"id": "u"})
    ids = [a["application_id"] for a in r["manifest"]["applications"]]
    assert ids == ["a-old-ghosted"], ids


# ----------------------------------------------------------------------
# Standards public page
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_standards_page_carries_rails_and_flags(monkeypatch):
    from domains.standards import service as std

    class _JobsColl:
        async def count_documents(self, q=None):
            if q and q.get("is_stale", {}).get("$ne") is True:
                return 21000
            return 25000
    class _DB:
        jobs = _JobsColl()
    monkeypatch.setattr(std, "get_db", lambda: _DB())

    r = await std.standards()
    # Phase 0-4 must all appear in phases_gated_pass (post-4 world).
    phases = [p["phase"] for p in r["phases_gated_pass"]]
    assert any("Phase 0" in p for p in phases)
    assert any("Phase 1" in p for p in phases)
    assert any("Phase 4" in p for p in phases)
    # Coverage numbers are the read-only aggregates.
    assert r["coverage"]["verified_providers"] == 16
    assert r["coverage"]["jobs_in_index"] == 25000
    assert r["coverage"]["fresh_jobs_in_index"] == 21000
    # Rails must include the core safety commitments.
    rails_by_name = {rail["rail"] for rail in r["rails"]}
    for req in ("email dispatch", "follow-ups", "apply cap",
                 "standing wave", "employer supply",
                 "eligibility engine", "evidence exports"):
        assert req in rails_by_name, (req, rails_by_name)
    # Feature flags: WEEKLY_DIGEST_EMAIL_ENABLED and WORKDAY_LIVE_ENABLED
    # must be listed (whether ON or OFF) so consumers see the state.
    flag_names = {f["flag"] for f in r["feature_flags"]}
    assert "WEEKLY_DIGEST_EMAIL_ENABLED" in flag_names
    assert "WORKDAY_LIVE_ENABLED" in flag_names
