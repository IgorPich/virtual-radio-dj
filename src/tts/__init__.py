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

        return ElevenLabsTTSProvider(
            api_key=config.elevenlabs_api_key,
            voice_id=config.elevenlabs_voice_id,
            model=config.elevenlabs_model,
        )

    if config.provider == "piper":
        from src.tts.piper_tts import PiperTTSProvider

        return PiperTTSProvider(
            model_path=config.piper_model_path,
            exe_path=config.piper_exe_path,
            speaker_id=config.piper_speaker_id,
        )

    raise ValueError(
        f"Unknown TTS provider '{config.provider}'. "
        "Valid options: 'local_gtts', 'elevenlabs', 'piper'."
    )


def create_cohost_tts_provider(config: TTSConfig) -> TTSProvider | None:
    """
    Return a Piper TTS provider for the co-host voice, or *None* if not configured.

    Only Piper is supported for the co-host because Piper is the only provider
    that supports running two independent model files side-by-side.
    """
    if not config.piper_model_path_cohost:
        return None

    from src.tts.piper_tts import PiperTTSProvider

    return PiperTTSProvider(
        model_path=config.piper_model_path_cohost,
        exe_path=config.piper_exe_path,
        speaker_id=None,
    )
