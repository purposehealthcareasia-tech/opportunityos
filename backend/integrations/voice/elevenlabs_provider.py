"""ElevenLabs voice provider adapter — Milestone H.

Real `text_to_speech()` code path. Hard-fails without credentials.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from integrations.base import (
    BaseProvider, ProviderCategory, HealthResult, TestResult, ConfigValidation,
    ProviderError,
)
from integrations import registry


log = logging.getLogger("oppos.integrations.elevenlabs")


class ElevenLabsProvider(BaseProvider):
    slug = "elevenlabs"
    label = "ElevenLabs"
    category = ProviderCategory.VOICE
    required_env = ("ELEVENLABS_API_KEY",)
    optional_env = ("ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID")
    docs_url = "https://elevenlabs.io/app/settings/api-keys"
    supports_test_mode = True

    _api_base = "https://api.elevenlabs.io/v1"

    def configure(self) -> None:
        self.config = {k: os.environ.get(k, "") for k in (*self.required_env, *self.optional_env)}

    def _detect_test_mode(self) -> bool:
        return bool(self.config.get("ELEVENLABS_API_KEY"))

    def _headers(self) -> dict[str, str]:
        return {"xi-api-key": self.config["ELEVENLABS_API_KEY"]}

    async def test_connection(self) -> TestResult:
        validation = self.validate_configuration()
        if not validation.ok:
            return TestResult(ok=False,
                              detail=f"CONFIGURATION_REQUIRED — set: {', '.join(validation.missing_env)}")
        try:
            t0 = time.time()
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(f"{self._api_base}/user", headers=self._headers())
            latency_ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                return TestResult(ok=True, detail="ElevenLabs /user OK.",
                                   latency_ms=latency_ms)
            return TestResult(ok=False, detail=f"ElevenLabs HTTP {r.status_code}.",
                               latency_ms=latency_ms)
        except Exception as e:
            return TestResult(ok=False, detail=f"probe_error: {str(e)[:200]}")

    async def text_to_speech(self, *, text: str, voice_id: str | None = None,
                                model_id: str | None = None) -> bytes:
        """Synthesise a short (<1KB) text into MP3 bytes. Hard-fails on
        `configuration_required`."""
        validation = self.validate_configuration()
        if not validation.ok:
            raise ProviderError("configuration_required",
                                 f"missing env: {', '.join(validation.missing_env)}",
                                 provider=self.slug)
        vid = voice_id or self.config.get("ELEVENLABS_VOICE_ID") or ""
        mid = model_id or self.config.get("ELEVENLABS_MODEL_ID") or "eleven_multilingual_v2"
        if not vid:
            raise ProviderError("configuration_required",
                                 "ELEVENLABS_VOICE_ID not set (or voice_id argument missing)",
                                 provider=self.slug)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"{self._api_base}/text-to-speech/{vid}",
                    json={"text": text, "model_id": mid,
                            "output_format": "mp3_44100_128"},
                    headers={**self._headers(),
                              "Accept": "audio/mpeg",
                              "Content-Type": "application/json"},
                )
            if not r.is_success:
                raise ProviderError("tts_failed",
                                     f"elevenlabs HTTP {r.status_code}: {r.text[:200]}",
                                     provider=self.slug, http_status=r.status_code,
                                     retryable=r.status_code >= 500)
            self.record_success()
            return r.content
        except ProviderError:
            raise
        except Exception as e:
            err = ProviderError("tts_error", str(e)[:200],
                                 provider=self.slug, retryable=True)
            self.record_error(err)
            raise err


registry.register(ElevenLabsProvider())
