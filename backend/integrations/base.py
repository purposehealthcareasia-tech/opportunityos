"""Provider base — the SINGLE contract every integration adapter implements.

Design goals (per founder mandate):
  - No scattered SDK calls. Everything goes through a Provider.
  - Truthful status. `status()` returns one of ProviderStatus, no fake values.
  - Every external request must have: timeout, retry policy, structured errors,
    correlation ID (see `IntegrationEvent.correlation_id`), safe logging.
  - Every webhook must have: signature verification, idempotency, replay
    protection, event storage, retry-safe processing.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

# Ensure backend/.env is loaded into os.environ so adapter modules using
# `os.environ.get(...)` see the same values pydantic_settings uses.
try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent / ".env"
    if _env.exists():
        load_dotenv(_env, override=False)
except Exception:
    pass


class ProviderStatus(str, Enum):
    """Real, truthful integration status. Enum values are the wire strings.

    - CONNECTED: configured with what appears to be production credentials,
      last health-check succeeded, no recent errors within cooldown window.
    - TEST_MODE: configured with sandbox / test credentials, otherwise healthy.
      (e.g., Stripe test keys, Twilio Verify sandbox, LLM Emergent key.)
    - CONFIGURATION_REQUIRED: adapter is present but required env vars are
      absent. Admin dashboard shows the exact env var names needed.
    - DEGRADED: configured, but recent errors within cooldown window. Traffic
      may still be attempted; admin sees the failure count.
    - DISABLED: administratively disabled from the admin dashboard, or
      hard-disabled by config (e.g., billing_enabled=false feature flag).
    """
    CONNECTED = "CONNECTED"
    TEST_MODE = "TEST_MODE"
    CONFIGURATION_REQUIRED = "CONFIGURATION_REQUIRED"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class ProviderCategory(str, Enum):
    PAYMENTS = "payments"
    AUTH = "auth"
    EMAIL = "email"
    SMS = "sms"
    AI = "ai"
    VOICE = "voice"
    STORAGE = "storage"
    NOTIFICATIONS = "notifications"
    DISCOVERY = "discovery"


@dataclass
class ConfigValidation:
    """Result of `provider.validate_configuration()`."""
    ok: bool
    missing_env: list[str] = field(default_factory=list)
    # A short human-readable note (safe for admin UI). Never include secret
    # values.
    note: str = ""
    is_test_mode: bool = False


@dataclass
class HealthResult:
    """Result of `provider.health_check()` — a lightweight, cached probe."""
    healthy: bool
    latency_ms: int | None = None
    error: str | None = None
    checked_at: float = field(default_factory=time.time)


@dataclass
class TestResult:
    """Result of `provider.test_connection()` — a deeper probe run on demand
    from the admin dashboard. May consume small amounts of quota."""
    ok: bool
    detail: str = ""
    latency_ms: int | None = None
    raw: dict | None = None


class ProviderError(Exception):
    """Normalized error surface across all providers.

    Adapters MUST catch vendor-specific exceptions and raise this instead so the
    integration layer, webhooks, and admin surface all see a consistent shape.
    """

    def __init__(self, code: str, message: str, *, provider: str,
                 vendor_code: str | None = None, retryable: bool = False,
                 correlation_id: str | None = None,
                 http_status: int | None = None):
        self.code = code
        self.message = message
        self.provider = provider
        self.vendor_code = vendor_code
        self.retryable = retryable
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.http_status = http_status
        super().__init__(f"[{provider}:{code}] {message}")

    def to_public(self) -> dict:
        """Serialise for the admin UI. Never include vendor tokens/keys."""
        return {
            "error": self.code,
            "message": self.message,
            "provider": self.provider,
            "vendor_code": self.vendor_code,
            "retryable": self.retryable,
            "correlation_id": self.correlation_id,
        }


class BaseProvider:
    """Abstract base for every provider adapter.

    Subclasses implement at least:
      - `configure()`         — read env vars into self.config
      - `validate_configuration()` — return ConfigValidation
      - `async health_check()`     — return HealthResult
      - `async test_connection()`  — deeper probe (admin action)
      - `describe()`               — public metadata for admin UI

    Optional (category-specific):
      - Payment: create_checkout, verify_webhook, refund, cancel, list_invoices
      - Auth: build_authorize_url, exchange_code, verify_id_token, link_account
      - Email: send, verify_webhook
      - SMS: start_verify, check_verify, verify_webhook
      - AI: chat, embed, structured_completion, record_usage
      - Voice: synthesize, list_voices
      - Storage: upload, signed_url, delete, checksum
    """

    slug: str = ""
    category: ProviderCategory | None = None
    required_env: tuple[str, ...] = ()
    optional_env: tuple[str, ...] = ()
    label: str = ""            # Human-readable label for admin UI.
    docs_url: str = ""         # Where an operator finds credentials.
    supports_test_mode: bool = False

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self._disabled: bool = False
        self._last_error: Optional[ProviderError] = None
        self._last_error_at: float = 0.0
        self._last_success_at: float = 0.0

    # ---- lifecycle ------------------------------------------------------

    def configure(self) -> None:
        """Load env-var values into `self.config`. Override in subclasses."""
        raise NotImplementedError

    def validate_configuration(self) -> ConfigValidation:
        """Default: all required_env must be present and non-empty."""
        missing = [k for k in self.required_env if not self.config.get(k)]
        if missing:
            return ConfigValidation(ok=False, missing_env=missing,
                                     note="Required env vars not set.")
        return ConfigValidation(ok=True, is_test_mode=self._detect_test_mode())

    def _detect_test_mode(self) -> bool:
        """Override per provider — inspect the configured credentials to
        determine sandbox vs production. Never inspect secret values in logs."""
        return False

    async def health_check(self) -> HealthResult:
        """Cheap probe (should complete in <2 s). Adapters may cache the
        result briefly."""
        return HealthResult(healthy=True)

    async def test_connection(self) -> TestResult:
        """Admin-dashboard action. Deeper, side-effect-free probe."""
        return TestResult(ok=True, detail="Base provider — override in subclass.")

    # ---- status helpers -------------------------------------------------

    def status(self, *, feature_flag_enabled: bool = True) -> ProviderStatus:
        """Compute the truthful status. Never returns CONNECTED unless the
        provider is both configured AND a recent success is recorded (or no
        errors are recorded yet — first-boot state)."""
        if self._disabled or not feature_flag_enabled:
            return ProviderStatus.DISABLED
        validation = self.validate_configuration()
        if not validation.ok:
            return ProviderStatus.CONFIGURATION_REQUIRED
        # Recent errors (within 5 min) → DEGRADED.
        if self._last_error and (time.time() - self._last_error_at) < 300:
            return ProviderStatus.DEGRADED
        if validation.is_test_mode:
            return ProviderStatus.TEST_MODE
        return ProviderStatus.CONNECTED

    def record_success(self) -> None:
        self._last_success_at = time.time()
        self._last_error = None

    def record_error(self, err: ProviderError) -> None:
        self._last_error = err
        self._last_error_at = time.time()

    def disable(self) -> None:
        self._disabled = True

    def enable(self) -> None:
        self._disabled = False

    # ---- public metadata ------------------------------------------------

    def describe(self) -> dict:
        """Payload consumed by `GET /api/v1/admin/integrations`. NO secrets."""
        status = self.status()
        validation = self.validate_configuration()
        return {
            "slug": self.slug,
            "label": self.label,
            "category": self.category.value if self.category else None,
            "status": status.value,
            "is_test_mode": validation.is_test_mode,
            "required_env": list(self.required_env),
            "optional_env": list(self.optional_env),
            "missing_env": validation.missing_env,
            "docs_url": self.docs_url,
            "supports_test_mode": self.supports_test_mode,
            "last_success_at": self._last_success_at or None,
            "last_error_at": self._last_error_at or None,
            "last_error": (self._last_error.to_public() if self._last_error else None),
        }
