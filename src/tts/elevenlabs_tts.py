"""ElevenLabs TTS stub — implement when upgrading to a paid voice service."""

from __future__ import annotations

from pathlib import Path

from src.tts.exceptions import TTSProviderNotImplementedError
from src.tts.provider import TTSProvider


class ElevenLabsTTSProvider(TTSProvider):
    """
    Placeholder for ElevenLabs premium TTS.

    To activate:
    1. ``pip install elevenlabs``
    2. Set ``ELEVENLABS_API_KEY`` in your ``.env``.
    3. Replace the ``NotImplementedError`` bodies with the real API calls.
    4. Update ``TTSConfig.provider`` to ``"elevenlabs"`` in ``.env``.
    5. Register this class in the provider factory in ``src/tts/__init__.py``.
    """

    async def synthesize(self, text: str, output_path: Path) -> bool:
        raise TTSProviderNotImplementedError(
            "ElevenLabsTTSProvider is a stub.  "
            "See class docstring for activation instructions."
        )

    async def estimate_duration(self, text: str) -> float:
        raise TTSProviderNotImplementedError(
            "ElevenLabsTTSProvider is a stub."
        )
