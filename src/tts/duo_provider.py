"""DuoTTSProvider — synthesizes two-voice dialogue into a single audio file."""

from __future__ import annotations

import re
import tempfile
import wave
from pathlib import Path

from src.tts.provider import TTSProvider
from src.utils.logger import get_logger

_logger = get_logger("tts.duo")

# Matches lines like "[RYAN]: some text" or "[PIOTR FRONCZEWSKI]: some text".
_SPEAKER_RE = re.compile(r"^\[([^\]]+)\]:\s*(.+)$", re.MULTILINE)


class DuoTTSProvider(TTSProvider):
    """
    Synthesizes a two-voice script into a single audio file.

    The input text may contain speaker markers in the form::

        [RYAN]: It's a great track, isn't it?
        [EMMA]: Absolutely — I've had it on repeat all week.

    Each tagged segment is synthesized with the matching voice provider and
    the resulting WAV clips are concatenated in order.  If no markers are
    found the entire text is delegated to ``voice_a``, making this a
    transparent drop-in for plain-text input.

    Both providers **must** produce WAV output (``audio_suffix == ".wav"``)
    with identical sample rate, channels, and bit-depth.

    Args:
        voice_a:  Primary voice provider (Ryan / host).
        voice_b:  Co-host voice provider (Emma).
        name_a:   Speaker label for *voice_a* (default ``"RYAN"``).
        name_b:   Speaker label for *voice_b* (default ``"EMMA"``).
    """

    def __init__(
        self,
        voice_a: TTSProvider,
        voice_b: TTSProvider,
        name_a: str = "RYAN",
        name_b: str = "EMMA",
    ) -> None:
        self._voice_a = voice_a
        self._voice_b = voice_b
        self._name_a = name_a.upper()
        self._name_b = name_b.upper()

    # ── TTSProvider interface ─────────────────────────────────────────

    @property
    def audio_suffix(self) -> str:
        return ".wav"

    async def synthesize(self, text: str, output_path: Path) -> bool:
        """
        Synthesize *text* to *output_path*.

        Detects speaker markers and routes each segment to the correct
        voice.  Falls back to ``voice_a`` for plain text.
        """
        segments = self._parse_segments(text)

        if not segments:
            # No markers — plain text, delegate entirely to voice_a.
            _logger.debug("DuoTTS: no speaker markers found, delegating to voice_a.")
            return await self._voice_a.synthesize(text, output_path)

        _logger.info("DuoTTS: synthesizing %d segments.", len(segments))
        tmp_paths: list[Path] = []
        try:
            for idx, (speaker, line) in enumerate(segments):
                provider = self._voice_b if speaker == self._name_b else self._voice_a
                with tempfile.NamedTemporaryFile(
                    suffix=".wav", delete=False, dir=tempfile.gettempdir()
                ) as tmp:
                    seg_path = Path(tmp.name)
                tmp_paths.append(seg_path)
                success = await provider.synthesize(line, seg_path)
                if not success:
                    _logger.error(
                        "DuoTTS: synthesis failed for segment %d ('%s').", idx, speaker
                    )
                    return False

            self._concatenate_wavs(tmp_paths, output_path)
            return output_path.exists()

        except Exception as exc:
            _logger.error("DuoTTS synthesis error: %s", exc, exc_info=True)
            return False
        finally:
            for p in tmp_paths:
                p.unlink(missing_ok=True)

    async def estimate_duration(self, text: str) -> float:
        """Estimate total duration by summing per-segment estimates."""
        segments = self._parse_segments(text)
        if not segments:
            return await self._voice_a.estimate_duration(text)
        total = 0.0
        for speaker, line in segments:
            provider = self._voice_b if speaker == self._name_b else self._voice_a
            total += await provider.estimate_duration(line)
        return total

    # ── Internal helpers ──────────────────────────────────────────────

    def _parse_segments(self, text: str) -> list[tuple[str, str]]:
        """
        Extract ``(speaker_label, line_text)`` pairs from a marked-up script.

        Returns an empty list if no markers are present.
        """
        matches = _SPEAKER_RE.findall(text)
        return [(name.upper(), line.strip()) for name, line in matches]

    @staticmethod
    def _concatenate_wavs(sources: list[Path], dest: Path) -> None:
        """
        Concatenate WAV files in *sources* into *dest*.

        All source files must share the same sample rate, channel count, and
        sample width.  The parameters are read from the first file.
        """
        if not sources:
            raise ValueError("No source WAV files to concatenate.")

        dest.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(sources[0]), "rb") as first:
            params = first.getparams()
            frames = first.readframes(first.getnframes())

        all_frames = bytearray(frames)

        for src in sources[1:]:
            with wave.open(str(src), "rb") as wf:
                # Validate compatibility.
                if (wf.getnchannels() != params.nchannels
                        or wf.getsampwidth() != params.sampwidth
                        or wf.getframerate() != params.framerate):
                    _logger.warning(
                        "DuoTTS: WAV params mismatch in '%s' — "
                        "audio may sound incorrect.", src.name
                    )
                all_frames.extend(wf.readframes(wf.getnframes()))

        with wave.open(str(dest), "wb") as out:
            out.setparams(params)
            out.writeframes(bytes(all_frames))
