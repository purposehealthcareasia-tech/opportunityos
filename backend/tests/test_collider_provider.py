"""No-network tests against Fynd's real provider and registry contracts."""
import time
from unittest.mock import patch

import pytest

from domains.collider.client import ColliderError
from integrations.base import ProviderStatus
from integrations.discovery.collider_provider import ColliderProvider


TOKEN = "c" * 48


def provider(**values):
    p = ColliderProvider()
    p.config = {"FYND_COLLIDER_BASE_URL": "https://collider.example.test",
                "FYND_COLLIDER_TOKEN": TOKEN, "FYND_COLLIDER_ENABLED": "true", **values}
    return p


def test_missing_configuration_never_looks_connected():
    p = provider(FYND_COLLIDER_TOKEN="")
    assert p.status() == ProviderStatus.CONFIGURATION_REQUIRED
    assert p.describe()["missing_env"] == ["FYND_COLLIDER_TOKEN"]


def test_credentials_without_probe_are_not_connected():
    assert provider().status() == ProviderStatus.DEGRADED


@pytest.mark.parametrize("value", ["", "false", "1", "yes"])
def test_probe_opt_in_is_explicit(value):
    p = provider(FYND_COLLIDER_ENABLED=value)
    p.enable()
    assert p.status() == ProviderStatus.DISABLED


def test_invalid_origin_is_configuration_required():
    p = provider(FYND_COLLIDER_BASE_URL="http://169.254.169.254")
    assert p.status() == ProviderStatus.CONFIGURATION_REQUIRED


def test_description_never_exposes_token_origin_or_fake_coverage():
    p = provider()
    d = p.describe()
    assert TOKEN not in str(d)
    assert "collider.example.test" not in str(d)
    assert d["internet_coverage_percent"] is None
    assert d["scan_enabled"] is False
    assert d["application_submission_enabled"] is False
    assert d["rollout_stage"] == "connection_only"


@pytest.mark.asyncio
async def test_missing_and_disabled_never_construct_network_client():
    with patch("integrations.discovery.collider_provider.ColliderClient") as client:
        for p in [provider(FYND_COLLIDER_TOKEN=""), provider(FYND_COLLIDER_ENABLED="false")]:
            assert not (await p.test_connection()).ok
            assert not (await p.health_check()).healthy
        p = provider()
        p.disable()
        assert not (await p.test_connection()).ok
        client.assert_not_called()


@pytest.mark.asyncio
async def test_success_checks_contract_but_does_not_unlock_scanning():
    with patch("integrations.discovery.collider_provider.ColliderClient") as factory:
        client = factory.return_value.__aenter__.return_value
        p = provider()
        result = await p.test_connection()
        assert result.ok
        client.health.assert_awaited_once()
        client.capabilities.assert_awaited_once()
        client.submit_run.assert_not_called()
        assert p.status() == ProviderStatus.CONNECTED
        assert p.describe()["scan_enabled"] is False
        p._last_success_at = time.time() - 301
        assert p.status() == ProviderStatus.DEGRADED


@pytest.mark.asyncio
async def test_failure_does_not_echo_upstream_information():
    with patch("integrations.discovery.collider_provider.ColliderClient") as factory:
        client = factory.return_value.__aenter__.return_value
        client.capabilities.side_effect = ColliderError("UPSTREAM_AUTH")
        p = provider()
        p.record_success()
        assert not (await p.test_connection()).ok
        assert p.status() == ProviderStatus.DEGRADED
        assert "UPSTREAM_AUTH" not in str(p.describe())
        assert TOKEN not in str(p.describe())


@pytest.mark.asyncio
async def test_boot_health_probe_is_network_free():
    with patch("integrations.discovery.collider_provider.ColliderClient") as factory:
        p = provider()
        assert not (await p.health_check()).healthy
        factory.assert_not_called()
