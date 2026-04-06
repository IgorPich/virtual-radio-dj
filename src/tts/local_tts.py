"""Local TTS implementation using gTTS (Google Translate TTS, free)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from gtts import gTTS

from src.tts.exceptions import TTSSynthesisError
from src.tts.provider import TTSProvider
from src.utils.logger import get_logger
from src.utils.timing_utils import words_to_seconds

_logger = get_logger("tts.local_gtts")

# gTTS speaks at roughly 150 WPM for English.
_GTTS_WPM = 150


class LocalGTTSProvider(TTSProvider):
    """
    Free text-to-speech using gTTS (wraps Google Translate's TTS API).

    Synthesis is I/O-bound and runs in a thread-pool executor to avoid
    blocking the asyncio event loop.

    Args:
        language: BCP-47 language code (default ``"en"``).
        slow:     When *True*, gTTS speaks at a reduced rate — useful for
                  clarity testing but noticeably slower.
    """

    def __init__(self, language: str = "en", slow: bool = False) -> None:
        self._language = language
        self._slow = slow

    async def synthesize(self, text: str, output_path: Path) -> bool:
        """
        Synthesize *text* to an MP3 file at *output_path*.

        The synthesis is executed in a thread-pool executor to keep the
        asyncio event loop free during the blocking network call.

        Args:
            text:        Text to speak.
            output_path: Destination ``.mp3`` file path.

        Returns:
            *True* if the file was created successfully.

        Raises:
            TTSSynthesisError: Propagated from gTTS on any failure.
        """
        _logger.info("Synthesizing TTS for %d chars → %s", len(text), output_path)
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._sync_synthesize, text, output_path)
        except Exception as exc:
            raise TTSSynthesisError(f"gTTS synthesis failed: {exc}") from exc

        exists = output_path.exists()
        if not exists:
            _logger.error("Synthesis appeared to succeed but output file is missing: %s", output_path)
        return exists

    async def estimate_duration(self, text: str) -> float:
        """
        Estimate speech duration from word count using the gTTS speaking rate.

        Args:
            text: Input text.

        Returns:
            Estimated seconds, with a 20 % safety margin.
        """
        base = words_to_seconds(text, wpm=_GTTS_WPM)
        if self._slow:
            base *= 1.4
        # Add 20 % overhead so ducking doesn't close before audio ends.
        return base * 1.2

    # ------------------------------------------------------------------ #
    # Internal helpers (run in executor — must be synchronous)            #
    # ------------------------------------------------------------------ #

    def _sync_synthesize(self, text: str, output_path: Path) -> None:
        """Blocking gTTS call (runs in thread executor)."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tts = gTTS(text=text, lang=self._language, slow=self._slow)
        tts.save(str(output_path))
