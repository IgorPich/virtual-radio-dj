"""ElevenLabs TTS provider — realistic text-to-speech via v1 REST API."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from src.tts.exceptions import TTSSynthesisError
from src.tts.provider import TTSProvider
from src.utils.logger import get_logger

_logger = get_logger("tts.elevenlabs")

_API_BASE = "https://api.elevenlabs.io/v1"

# Average speaking rate for duration estimation (words per minute).
_ELEVENLABS_WPM = 150


class ElevenLabsTTSProvider(TTSProvider):
    """
    ElevenLabs premium TTS using the v1 REST API.

    Sends text to the ``/v1/text-to-speech/{voice_id}`` endpoint and
    streams the returned MP3 audio to disk.  Uses ``httpx`` (already a
    project dependency) instead of the heavyweight ``elevenlabs`` SDK.

    Args:
        api_key:  ElevenLabs API key.
        voice_id: Target voice identifier.
        model:    Model to use (default ``eleven_turbo_v2_5``).
    """

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model: str = "eleven_turbo_v2_5",
    ) -> None:
        if not api_key:
            raise ValueError(
                "ElevenLabs API key is required.  "
                "Set TTS__ELEVENLABS_API_KEY in your .env file."
            )
        if not voice_id:
            raise ValueError(
                "ElevenLabs voice ID is required.  "
                "Set TTS__ELEVENLABS_VOICE_ID in your .env file."
            )
        self._api_key = api_key
        self._voice_id = voice_id
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=_API_BASE,
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    async def synthesize(self, text: str, output_path: Path) -> bool:
        """
        Convert *text* to speech via ElevenLabs and write the MP3 to *output_path*.

        Returns *True* on success, *False* on failure (logged but not raised
        so the orchestrator can skip gracefully).
        """
        url = f"/text-to-speech/{self._voice_id}"
        payload = {
            "text": text,
            "model_id": self._model,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }

        try:
            response = await self._client.post(url, json=payload)

            if response.status_code == 401:
                _logger.error(
                    "ElevenLabs authentication failed — check TTS__ELEVENLABS_API_KEY."
                )
                return False
            if response.status_code == 429:
                _logger.warning("ElevenLabs rate limit reached — skipping synthesis.")
                return False
            if response.status_code != 200:
                _logger.error(
                    "ElevenLabs API error %d: %s",
                    response.status_code,
                    response.text[:300],
                )
                return False

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)
            _logger.debug("ElevenLabs audio written to %s.", output_path)
            return True

        except httpx.TimeoutException:
            _logger.error("ElevenLabs request timed out.")
            return False
        except httpx.HTTPError as exc:
            _logger.error("ElevenLabs HTTP error: %s", exc)
            return False

    async def estimate_duration(self, text: str) -> float:
        """
        Estimate audio duration from word count.

        Uses the same heuristic as the local gTTS provider —
        ~150 WPM plus a 20 % safety margin for ducking sizing.
        """
        word_count = len(text.split())
        base = (word_count / _ELEVENLABS_WPM) * 60.0
        return base * 1.2

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
