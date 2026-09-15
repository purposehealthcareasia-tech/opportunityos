"""Synthetic privacy checks; never connect to or erase a real database."""
import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from domains.research_reports.privacy import erase_account_reports, report_export_index


class ResearchPrivacyTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_is_owner_scoped_metadata_with_explicit_separate_content(self):
        db = types.SimpleNamespace(research_report_buckets=object())
        receipt = {"id": "12345678-1234-1234-1234-123456789abc", "title": "Synthetic", "saved_at": "2026-09-13T00:00:00Z", "byte_size": 20}
        with patch("domains.research_reports.privacy.ResearchReportService") as service:
            service.return_value.list = AsyncMock(return_value={"reports": [receipt], "used_bytes": 20, "limits": {}})
            exported = await report_export_index(db, "owner-a")
            service.assert_called_once_with(db.research_report_buckets)
            service.return_value.list.assert_awaited_once_with("owner-a")
        self.assertIs(exported["content_included"], False)
        self.assertIn("Download bundle", exported["download_instructions"])
        self.assertEqual(exported["reports"][0]["download_path"], "/api/v1/research/reports/" + receipt["id"])
        self.assertNotIn("bundle", exported["reports"][0])

    async def test_erasure_targets_only_exact_owner_bucket(self):
        bucket = types.SimpleNamespace(delete_one=AsyncMock())
        await erase_account_reports(types.SimpleNamespace(research_report_buckets=bucket), "owner-a")
        bucket.delete_one.assert_awaited_once_with({"_id": "owner-a"})


class InstalledResearchWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_cache_cannot_skip_report_auth_or_resurrect_deleted_receipt(self):
        backend = Path(__file__).resolve().parents[1]
        path = backend / "middleware/idempotency.py"
        if not path.exists():
            self.skipTest("Run this installed-wiring check in the actual Fynd backend")
        from starlette.requests import Request
        from starlette.responses import Response
        core = types.ModuleType("core")
        core.__path__ = []
        db = types.ModuleType("core.db")
        def forbidden_db():
            raise AssertionError("Legacy cache must not be touched for report routes")
        db.get_db = forbidden_db
        config = types.ModuleType("core.config")
        config.settings = types.SimpleNamespace(SESSION_COOKIE_NAME="synthetic_session")
        security = types.ModuleType("core.security")
        security.decode_access_token = lambda _: None
        sessions = types.ModuleType("core.sessions")
        sessions.get_session = AsyncMock(side_effect=AssertionError("Legacy auth must not run"))
        time_utils = types.ModuleType("core.time_utils")
        time_utils.utc_now = lambda: None
        core.sessions = sessions
        spec = importlib.util.spec_from_file_location("isolated_report_idempotency", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"core": core, "core.db": db, "core.config": config, "core.security": security, "core.sessions": sessions, "core.time_utils": time_utils}):
            spec.loader.exec_module(module)
        middleware = module.IdempotencyMiddleware(lambda *_: None)
        for route in ["/api/v1/research/reports", "/api/v1/research/reports/12345678-1234-1234-1234-123456789abc"]:
            request = Request({"type": "http", "method": "POST", "path": route, "headers": [(b"idempotency-key", b"synthetic-old-cache-key")], "query_string": b""})
            fresh_auth = AsyncMock(return_value=Response(status_code=401))
            result = await middleware.dispatch(request, fresh_auth)
            self.assertEqual(result.status_code, 401)
            fresh_auth.assert_awaited_once_with(request)

    async def test_actual_server_mount_and_privacy_hooks_exist(self):
        backend = Path(__file__).resolve().parents[1]
        server = backend / "server.py"
        privacy = backend / "domains/privacy/service.py"
        if not server.exists() or not privacy.exists():
            self.skipTest("Run this installed-wiring check in the actual Fynd backend")
        server_tree = ast.parse(server.read_text())
        self.assertTrue(any(isinstance(n, ast.ImportFrom) and n.module == "domains.research_reports.router" for n in ast.walk(server_tree)))
        self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "include_router" and any(isinstance(a, ast.Name) and a.id == "research_reports_router" for a in n.args) for n in ast.walk(server_tree)))
        privacy_tree = ast.parse(privacy.read_text())
        functions = {n.name: n for n in privacy_tree.body if isinstance(n, ast.AsyncFunctionDef)}
        for function, target in [("_build_bundle", "report_export_index"), ("sweep_expired_deletions", "erase_account_reports")]:
            self.assertTrue(any(isinstance(n, ast.Await) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name) and n.value.func.id == target for n in ast.walk(functions[function])))


if __name__ == "__main__":
    unittest.main()
