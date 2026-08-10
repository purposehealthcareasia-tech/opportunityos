"""Milestone J · ElevenLabs voice provider adapter contract tests.

Explicitly honest scope: these tests validate the ADAPTER CONTRACT — the
promises the provider makes to the integrations layer and admin dashboard
— not that live ElevenLabs TTS produces audio. Live-audio requires
`ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` env vars that are
CONFIGURATION_REQUIRED in preview by design.

What IS verified here:
  - Registry wiring (adapter picked up on import).
  - Provider metadata (slug, label, category, required_env, optional_env,
    docs_url, supports_test_mode).
  - `validate_configuration()` accurately reports missing env with the
    exact env-var names an operator needs to set.
  - `test_connection()` returns a well-shaped TestResult(ok=False,
    detail="CONFIGURATION_REQUIRED — set: ELEVENLABS_API_KEY") when unset.
  - `text_to_speech()` HARD-FAILS with ProviderError(code=
    "configuration_required") when env is missing — no fake bytes, no
    silent degrade.
  - When credentials ARE present (mocked env), text_to_speech() calls
    the right URL with the right body, and returns response bytes.
  - Error paths: 4xx → ProviderError(code="tts_failed", retryable=False);
    5xx → ProviderError(retryable=True); network exception →
    ProviderError(code="tts_error", retryable=True).

What is NOT verified (honest gap):
  - Actual audio content matches the input text (would require a real API).
  - The MP3 output plays back cleanly (would require an audio decoder).
  - ELEVENLABS_MODEL_ID overriding behavior on live output.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from integrations import registry
from integrations.base import (
    ProviderCategory,
    ProviderError,
    ProviderStatus,
    ConfigValidation,
    TestResult,
)
from integrations.voice.elevenlabs_provider import ElevenLabsProvider


# ---------------------------------------------------------------------------
# 1. Registry wiring
# ---------------------------------------------------------------------------
def test_provider_registered_on_import():
    """The `registry.register(ElevenLabsProvider())` at import-time must
    make the provider retrievable by slug."""
    provider = registry.get("elevenlabs")
    assert provider is not None, "elevenlabs provider not in registry"
    assert isinstance(provider, ElevenLabsProvider)


def test_provider_appears_in_category_listing():
    """Any code enumerating VOICE providers should find ElevenLabs."""
    all_providers = registry.all_providers()
    voice_providers = [p for p in all_providers if p.category == ProviderCategory.VOICE]
    slugs = {p.slug for p in voice_providers}
    assert "elevenlabs" in slugs


# ---------------------------------------------------------------------------
# 2. Provider metadata (admin UI contract)
# ---------------------------------------------------------------------------
def test_provider_metadata_shape():
    p = ElevenLabsProvider()
    assert p.slug == "elevenlabs"
    assert p.label == "ElevenLabs"
    assert p.category == ProviderCategory.VOICE
    assert "ELEVENLABS_API_KEY" in p.required_env
    assert "ELEVENLABS_VOICE_ID" in p.optional_env
    assert "ELEVENLABS_MODEL_ID" in p.optional_env
    assert p.docs_url == "https://elevenlabs.io/app/settings/api-keys"
    assert p.supports_test_mode is True


# ---------------------------------------------------------------------------
# 3. Configuration validation — the HONEST truth-teller
# ---------------------------------------------------------------------------
def test_validate_configuration_missing_env_reports_exact_key_name(monkeypatch):
    """When ELEVENLABS_API_KEY is unset, validation must list it by name so
    the admin UI can render the exact env-var operator needs to set."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    p = ElevenLabsProvider()
    p.configure()
    result = p.validate_configuration()
    assert result.ok is False
    assert result.missing_env == ["ELEVENLABS_API_KEY"]


def test_validate_configuration_present_env_returns_ok(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test_dummy")
    p = ElevenLabsProvider()
    p.configure()
    result = p.validate_configuration()
    assert result.ok is True
    assert result.missing_env == [] or result.missing_env is None or not result.missing_env


# ---------------------------------------------------------------------------
# 4. test_connection() — admin-dashboard probe contract
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_test_connection_configuration_required_when_unset(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    p = ElevenLabsProvider()
    p.configure()
    result = await p.test_connection()
    assert isinstance(result, TestResult)
    assert result.ok is False
    assert "CONFIGURATION_REQUIRED" in result.detail
    assert "ELEVENLABS_API_KEY" in result.detail  # the exact name


@pytest.mark.asyncio
async def test_test_connection_hits_user_endpoint_when_configured(monkeypatch):
    """With key set, test_connection() must probe /v1/user with the xi-api-key
    header. This locks the admin-dashboard probe contract."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test_dummy")
    p = ElevenLabsProvider()
    p.configure()

    captured = {}
    class _MockResp:
        status_code = 200
        text = "ok"
        content = b""
    class _MockClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_a): pass
        async def get(self, url, headers=None, **_kw):
            captured["url"] = url
            captured["headers"] = headers
            return _MockResp()
    with patch("integrations.voice.elevenlabs_provider.httpx.AsyncClient", _MockClient):
        result = await p.test_connection()
    assert result.ok is True
    assert captured["url"].endswith("/v1/user")
    assert captured["headers"].get("xi-api-key") == "sk_test_dummy"
    assert result.latency_ms is not None and result.latency_ms >= 0


# ---------------------------------------------------------------------------
# 5. text_to_speech() — the honest-failure contract
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tts_hard_fails_configuration_required_when_key_missing(monkeypatch):
    """No API key → hard-fail with the canonical error code. Never returns
    fake bytes, never silently degrades to a placeholder."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    p = ElevenLabsProvider()
    p.configure()
    with pytest.raises(ProviderError) as exc:
        await p.text_to_speech(text="hello")
    assert exc.value.code == "configuration_required"
    assert exc.value.provider == "elevenlabs"
    assert "ELEVENLABS_API_KEY" in exc.value.message


@pytest.mark.asyncio
async def test_tts_hard_fails_configuration_required_when_voice_id_missing(monkeypatch):
    """API key present, voice ID missing → configuration_required with a
    specific message pointing to the missing param. No fake bytes."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test_dummy")
    monkeypatch.delenv("ELEVENLABS_VOICE_ID", raising=False)
    p = ElevenLabsProvider()
    p.configure()
    with pytest.raises(ProviderError) as exc:
        await p.text_to_speech(text="hello")
    assert exc.value.code == "configuration_required"
    assert "ELEVENLABS_VOICE_ID" in exc.value.message


@pytest.mark.asyncio
async def test_tts_success_path_calls_correct_url_and_body(monkeypatch):
    """Given configured env + a working mocked http client, text_to_speech()
    must POST to /v1/text-to-speech/{voice_id} with the ElevenLabs body
    contract (text + model_id + output_format=mp3_44100_128) and return
    the response bytes verbatim."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test_dummy")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice_abc123")
    monkeypatch.setenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")

    captured = {}
    fake_audio = b"\xff\xfb\x90\x00" + b"MOCK_MP3_BYTES" * 4
    class _MockResp:
        status_code = 200
        is_success = True
        content = fake_audio
        text = ""
    class _MockClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_a): pass
        async def post(self, url, json=None, headers=None, **_kw):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _MockResp()

    p = ElevenLabsProvider()
    p.configure()
    with patch("integrations.voice.elevenlabs_provider.httpx.AsyncClient", _MockClient):
        result = await p.text_to_speech(text="hello world")

    assert result == fake_audio
    assert captured["url"].endswith("/v1/text-to-speech/voice_abc123")
    assert captured["json"] == {
        "text": "hello world",
        "model_id": "eleven_multilingual_v2",
        "output_format": "mp3_44100_128",
    }
    # Must send the xi-api-key + explicit Accept: audio/mpeg (MP3 out).
    assert captured["headers"].get("xi-api-key") == "sk_test_dummy"
    assert captured["headers"].get("Accept") == "audio/mpeg"


# ---------------------------------------------------------------------------
# 6. text_to_speech() — error surface contract
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tts_4xx_raises_non_retryable_provider_error(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test_dummy")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice_abc123")

    class _MockResp:
        status_code = 401
        is_success = False
        text = "unauthorized"
        content = b""
    class _MockClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_a): pass
        async def post(self, *_a, **_kw): return _MockResp()

    p = ElevenLabsProvider()
    p.configure()
    with patch("integrations.voice.elevenlabs_provider.httpx.AsyncClient", _MockClient):
        with pytest.raises(ProviderError) as exc:
            await p.text_to_speech(text="hi")
    assert exc.value.code == "tts_failed"
    assert exc.value.http_status == 401
    assert exc.value.retryable is False


@pytest.mark.asyncio
async def test_tts_5xx_raises_retryable_provider_error(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test_dummy")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice_abc123")

    class _MockResp:
        status_code = 503
        is_success = False
        text = "service unavailable"
        content = b""
    class _MockClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_a): pass
        async def post(self, *_a, **_kw): return _MockResp()

    p = ElevenLabsProvider()
    p.configure()
    with patch("integrations.voice.elevenlabs_provider.httpx.AsyncClient", _MockClient):
        with pytest.raises(ProviderError) as exc:
            await p.text_to_speech(text="hi")
    assert exc.value.code == "tts_failed"
    assert exc.value.http_status == 503
    assert exc.value.retryable is True


@pytest.mark.asyncio
async def test_tts_network_exception_raises_retryable_tts_error(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "sk_test_dummy")
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voice_abc123")

    class _ExplodingClient:
        def __init__(self, *_a, **_kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *_a): pass
        async def post(self, *_a, **_kw):
            raise ConnectionError("network down")

    p = ElevenLabsProvider()
    p.configure()
    with patch("integrations.voice.elevenlabs_provider.httpx.AsyncClient", _ExplodingClient):
        with pytest.raises(ProviderError) as exc:
            await p.text_to_speech(text="hi")
    assert exc.value.code == "tts_error"
    assert exc.value.retryable is True
    assert "network down" in exc.value.message
