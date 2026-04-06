"""Text-to-speech package."""

from __future__ import annotations

from src.config.schemas import TTSConfig
from src.tts.provider import TTSProvider


def create_tts_provider(config: TTSConfig) -> TTSProvider:
    """
    Factory that returns the correct :class:`TTSProvider` for *config*.

    Args:
        config: Validated TTS configuration.

    Returns:
        Concrete provider instance.

    Raises:
        ValueError: If ``config.provider`` names an unknown back-end.
    """
    if config.provider == "local_gtts":
        from src.tts.local_tts import LocalGTTSProvider

        return LocalGTTSProvider(language=config.language, slow=config.slow)

    if config.provider == "elevenlabs":
        from src.tts.elevenlabs_tts import ElevenLabsTTSProvider

        return ElevenLabsTTSProvider()

    raise ValueError(
        f"Unknown TTS provider '{config.provider}'. "
        "Valid options: 'local_gtts', 'elevenlabs'."
    )
