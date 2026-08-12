"""Regression guard for the Tier 2 refactor of `core.db.ensure_indexes`.

Pre-refactor (SHA `38fab8f1`) the function was 100+ linear lines. Post-refactor
it dispatches through 10 helpers. This test locks that the OBSERVABLE sequence
of `create_index` calls against every collection is byte-identical — same
collection names, same key specs, same option kwargs, same order.

If a future contributor rearranges the groups without thinking, or drops an
index, or adds one to the wrong group, this test fails with a precise diff.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from core import db as db_module


# --------------------------------------------------------------------------- #
# EXPECTED sequence — captured from HEAD 38fab8f1 (pre-refactor). Format:
#   (collection_name, tuple(args), tuple(sorted kwargs.items()))
# Composite key specs are compared as-is (order-sensitive, matches the exact
# Mongo semantics). Sorted kwargs.items() so dict-order changes don't create
# false diffs while still catching value changes.
# --------------------------------------------------------------------------- #
EXPECTED_INDEX_CALLS = [
    ("users",                ("email",), (("unique", True),)),
    ("consent_records",      ([("user_id", 1), ("scope", 1), ("ts", -1)],), ()),
    ("authorization_scopes", ([("user_id", 1), ("kind", 1), ("target", 1)],), ()),
    ("audit_logs",           ([("actor", 1), ("ts", -1)],), ()),
    ("audit_logs",           ([("object_ref", 1), ("ts", -1)],), ()),
    ("admin_users",          ("user_id",), (("unique", True),)),
    ("documents",            ("user_id",), ()),
    ("documents",            ("sha256",), ()),
    ("documents",            ("parse_status",), ()),
    ("resume_versions",      ([("user_id", 1), ("base", 1)],), ()),
    ("preferences",          ([("user_id", 1), ("version", -1)],), ()),
    ("eligibility_profiles", ([("user_id", 1), ("version", -1)],), ()),
    ("claims",               ([("user_id", 1), ("type", 1)],), ()),
    ("claims",               ([("user_id", 1), ("status", 1)],), ()),
    ("claims",               ("superseded_by",), ()),
    ("taxonomy",             ("family",), (("unique", True),)),
    ("companies",            ("domain",), (("unique", True),)),
    ("jobs",                 ("canonical_key",), (("unique", True),)),
    ("jobs",                 ("status",), ()),
    ("jobs",                 ("taxonomy_family",), ()),
    ("idempotency_records",  ("key",), (("unique", True),)),
    ("idempotency_records",  ("created_at",), (("expireAfterSeconds", 604800),)),
    ("applications",         ([("user_id", 1), ("job_id", 1)],), ()),
    ("applications",         ([("user_id", 1), ("job_id", 1)],),
                             (("name", "uniq_open_app_per_user_job"),
                              ("partialFilterExpression",
                               {"state": {"$in": ["shortlisted", "preparing", "awaiting_approval",
                                                  "approved", "submitting", "submitted", "response",
                                                  "interview", "offer"]}}),
                              ("unique", True))),
    ("applications",         ([("user_id", 1), ("state", 1)],), ()),
    ("match_scores",         ([("user_id", 1), ("job_id", 1)],), (("unique", True),)),
    ("match_scores",         ([("user_id", 1), ("score", -1)],), ()),
    ("hidden_jobs",          ([("user_id", 1), ("job_id", 1)],), (("unique", True),)),
    ("usage_meters",         ([("user_id", 1), ("period", 1)],), (("unique", True),)),
    ("score_feedback",       ([("user_id", 1), ("match_score_id", 1)],), ()),
    ("jobs",                 ("last_verified",), ()),
    ("submission_receipts",  ([("user_id", 1), ("company_id", 1), ("req_ref", 1)],),
                             (("name", "uniq_receipt_per_user_company_req"), ("unique", True))),
    ("llm_costs",            ([("user_id", 1), ("ts", -1)],), ()),
    ("llm_costs",            ([("task", 1), ("ts", -1)],), ()),
    ("ai_generations",       ([("user_id", 1), ("ts", -1)],), ()),
    ("ai_generations",       ([("application_id", 1), ("ts", -1)],), ()),
    ("screening_answers",    ([("user_id", 1), ("application_id", 1), ("question_id", 1)],),
                             (("name", "uniq_answer_per_app_question"),
                              ("partialFilterExpression", {"application_id": {"$type": "string"}}),
                              ("unique", True))),
    ("screening_answers",    ([("user_id", 1), ("application_id", 1)],), ()),
    ("resume_versions",      ([("user_id", 1), ("base", 1)],), ()),
    ("resume_versions",      ([("application_id", 1)],), ()),
    ("authorization_scopes", ([("user_id", 1), ("target", 1), ("created_at", -1)],),
                             (("name", "auth_scope_latest_lookup"),)),
    ("subscriptions",        ("user_id",), (("unique", True),)),
    ("outcomes",             ([("user_id", 1), ("application_id", 1), ("ts", -1)],), ()),
    ("outcomes",             ([("user_id", 1), ("ext_message_id", 1)],),
                             (("name", "uniq_outcome_per_user_ext_msg"),
                              ("partialFilterExpression", {"ext_message_id": {"$type": "string"}}),
                              ("unique", True))),
    ("interviews",           ([("user_id", 1), ("application_id", 1)],), ()),
    ("manual_queue_items",   ([("user_id", 1), ("state", 1)],), ()),
    ("manual_queue_items",   ("application_id",), (("unique", True),)),
    ("submission_receipts",  ([("user_id", 1), ("ts", -1)],), (("name", "receipts_by_user_ts"),)),
    ("feature_flags",        ("name",), (("unique", True),)),
    ("payment_transactions", ("session_id",), (("unique", True),)),
    ("payment_transactions", ([("user_id", 1), ("created_at", -1)],), ()),
    ("support_tickets",      ([("user_id", 1), ("created_at", -1)],), ()),
    ("export_jobs",          ([("user_id", 1), ("created_at", -1)],), ()),
    ("internal_analytics_events", ([("ts", -1)],), ()),
    ("internal_error_events",     ([("ts", -1)],), ()),
    ("walkins",              ([("user_id", 1), ("walked_in_at", -1)],), ()),
    ("walkins",              ([("user_id", 1), ("created_at", -1)],), ()),
    ("walkins",              ("application_id",), ()),
    ("personas",             ([("user_id", 1), ("created_at", -1)],), ()),
    ("personas",             ([("user_id", 1), ("superseded_by", 1)],), ()),
    ("discovery_runs",       ([("ts", -1)],), ()),
    ("jobs",                 ("first_seen",), ()),
    # Phase 6d — Application Credits (added 2026-08-12):
    ("application_credits_balance", ([("user_id", 1)],), (("unique", True),)),
    ("application_credits_ledger",  ([("user_id", 1), ("receipt_id", 1), ("direction", 1)],),
                                    (("name", "credits_ledger_debit_unique"),
                                     ("partialFilterExpression",
                                      {"receipt_id": {"$type": "string"}}),
                                     ("unique", True))),
    ("application_credits_ledger",  ([("user_id", 1), ("ts", -1)],), ()),
    ("application_credits_ledger",  ([("user_id", 1), ("source", 1), ("month_key", 1)],),
                                    (("name", "credits_ledger_monthly_refill_idempotent"),
                                     ("partialFilterExpression", {"source": "monthly_refill"}))),
]


class _RecordingCollection:
    def __init__(self, name: str, recorder: list):
        self._name = name
        self._recorder = recorder

    async def create_index(self, *args, **kwargs):
        self._recorder.append(
            (self._name, tuple(args), tuple(sorted(kwargs.items())))
        )
        return f"idx_{self._name}_{len(self._recorder)}"


class _RecordingDB:
    def __init__(self):
        self._calls: list = []

    def __getattr__(self, name: str) -> _RecordingCollection:
        return _RecordingCollection(name, self._calls)


@pytest.mark.asyncio
async def test_ensure_indexes_sequence_byte_identical(monkeypatch):
    """Refactor of ensure_indexes into 10 helpers must produce the exact
    same OBSERVABLE sequence of create_index calls as pre-refactor.
    """
    recorder = _RecordingDB()
    monkeypatch.setattr(db_module, "get_db", lambda: recorder)

    await db_module.ensure_indexes()

    assert recorder._calls == EXPECTED_INDEX_CALLS, (
        f"ensure_indexes call sequence drifted from pre-refactor baseline.\n"
        f"First difference at position {next((i for i,(a,b) in enumerate(zip(recorder._calls, EXPECTED_INDEX_CALLS)) if a != b), 'N/A')}"
    )
    # Also lock the total count so a helper adding an unlisted index fails immediately.
    assert len(recorder._calls) == len(EXPECTED_INDEX_CALLS) == 66


def test_ensure_indexes_helpers_are_all_wired():
    """Every module-level `_ensure_*_indexes` coroutine MUST appear in
    _ENSURE_INDEX_GROUPS. Prevents a new helper from being defined and
    silently never called."""
    module_helpers = {
        name for name in dir(db_module)
        if name.startswith("_ensure_") and name.endswith("_indexes")
        and callable(getattr(db_module, name))
    }
    wired = {fn.__name__ for fn in db_module._ENSURE_INDEX_GROUPS}
    assert module_helpers == wired, (
        f"Helper drift: defined={module_helpers}, wired={wired}"
    )
