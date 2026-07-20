"""Email/password — always-on native auth provider.

Not a stub: this is the current v0.1 auth mechanism. Reports CONNECTED
whenever the server has a JWT secret + bcrypt available."""
from __future__ import annotations

import os
from integrations.base import (
    BaseProvider, ProviderCategory, ConfigValidation, HealthResult, TestResult,
)
from integrations import registry


class EmailPasswordAuthProvider(BaseProvider):
    slug = "email_password"
    label = "Email + password (native)"
    category = ProviderCategory.AUTH
    required_env = ("JWT_SECRET",)
    optional_env = ("SESSION_TTL_HOURS",)
    docs_url = ""

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in
                        (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        # Dev fallback secret means non-production. Real prod uses the rotated
        # 64-byte secret.
        return (self.config.get("JWT_SECRET") or "") in {"dev-change-me", ""}

    async def health_check(self) -> HealthResult:
        try:
            import bcrypt, jwt  # noqa: F401
        except Exception as e:  # noqa: BLE001
            return HealthResult(healthy=False, error=f"import_failed: {e}")
        if not self.config.get("JWT_SECRET"):
            return HealthResult(healthy=False, error="JWT_SECRET missing")
        return HealthResult(healthy=True)

    async def test_connection(self) -> TestResult:
        try:
            import bcrypt
            h = bcrypt.hashpw(b"test-probe", bcrypt.gensalt())
            ok = bcrypt.checkpw(b"test-probe", h)
        except Exception as e:  # noqa: BLE001
            return TestResult(ok=False, detail=f"bcrypt roundtrip failed: {e}")
        return TestResult(ok=ok, detail="bcrypt roundtrip OK.")


registry.register(EmailPasswordAuthProvider())
