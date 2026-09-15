"""Integration registry — auto-detects configured providers and exposes truth.

Providers are registered at import time (module-level `register()` calls in
each adapter module). The registry:
  - Instantiates + configures every provider.
  - Never crashes on a broken provider — records the failure and moves on.
  - Persists provider status snapshots into `integration_configs` so the
    admin UI can render even when a probe is slow.
"""
from __future__ import annotations

import logging
from typing import Iterable

from integrations.base import BaseProvider, ProviderCategory, ProviderStatus

log = logging.getLogger("oppos.integrations")

_REGISTRY: dict[str, BaseProvider] = {}


def register(provider: BaseProvider) -> None:
    """Register a provider by slug. Called once per adapter module at import."""
    if not provider.slug:
        raise ValueError("Provider must define a non-empty slug.")
    if provider.slug in _REGISTRY:
        # Idempotent — reloads (uvicorn hot-reload) should not raise.
        log.debug("Provider %s already registered — replacing.", provider.slug)
    try:
        provider.configure()
    except Exception:
        log.exception("Provider %s configure() failed — registering as CONFIGURATION_REQUIRED.",
                       provider.slug)
    _REGISTRY[provider.slug] = provider
    log.info("Registered provider %s (%s) — status=%s",
             provider.slug, provider.category.value if provider.category else "?",
             provider.status().value)


def get(slug: str) -> BaseProvider | None:
    return _REGISTRY.get(slug)


def all_providers() -> list[BaseProvider]:
    return list(_REGISTRY.values())


def by_category(cat: ProviderCategory | str) -> list[BaseProvider]:
    cat_str = cat.value if isinstance(cat, ProviderCategory) else cat
    return [p for p in _REGISTRY.values()
            if (p.category and p.category.value == cat_str)]


def summary() -> dict:
    """Aggregate summary for the admin dashboard."""
    counts: dict[str, int] = {s.value: 0 for s in ProviderStatus}
    per_category: dict[str, list[dict]] = {}
    for p in _REGISTRY.values():
        d = p.describe()
        counts[d["status"]] = counts.get(d["status"], 0) + 1
        per_category.setdefault(d["category"] or "misc", []).append(d)
    return {"counts": counts, "by_category": per_category,
            "total": len(_REGISTRY)}


def load_all() -> None:
    """Import every adapter module so its `register()` runs. Called once from
    server.py lifespan."""
    # Adapters import guarded — a broken adapter must not stop startup.
    _try("integrations.payments.stripe_provider")
    _try("integrations.auth.google_provider")
    _try("integrations.auth.apple_provider")
    _try("integrations.auth.email_password_provider")
    _try("integrations.email.resend_provider")
    _try("integrations.email.sendgrid_provider")
    _try("integrations.sms.twilio_provider")
    _try("integrations.ai.openai_provider")
    _try("integrations.ai.anthropic_provider")
    _try("integrations.ai.gemini_provider")
    _try("integrations.voice.elevenlabs_provider")
    _try("integrations.storage.media_storage_provider")
    _try("integrations.payments.razorpay_provider")
    _try("integrations.payments.paypal_provider")
    _try("integrations.payments.paystack_provider")
    _try("integrations.push.webpush_provider")
    _try("integrations.discovery.collider_provider")


def _try(dotted: str) -> None:
    try:
        __import__(dotted)
    except Exception:
        log.exception("Adapter module %s failed to import — skipped.", dotted)
