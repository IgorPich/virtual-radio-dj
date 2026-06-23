"""Unit tests for DuoTTSProvider."""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.tts.duo_provider import DuoTTSProvider
from src.tts.provider import TTSProvider


def _make_voice(suffix: str = ".wav", duration: float = 1.0) -> AsyncMock:
    """Return a mock TTSProvider that creates a minimal valid WAV on synthesize."""
    voice = AsyncMock(spec=TTSProvider)
    voice.audio_suffix = suffix
    voice.estimate_duration.return_value = duration

    async def _synth(text: str, output_path: Path) -> bool:
        _write_silent_wav(output_path, frames=1600)  # ~0.1 s at 16 kHz mono
        return True

    voice.synthesize.side_effect = _synth
    return voice


def _write_silent_wav(path: Path, frames: int = 1600) -> None:
    """Write a minimal silent mono 16-bit 16 kHz WAV file."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16_000)
        wf.writeframes(b"\x00\x00" * frames)


class TestParseSegments:
    def test_empty_for_plain_text(self) -> None:
        provider = DuoTTSProvider(_make_voice(), _make_voice())
        assert provider._parse_segments("Hello, world!") == []

    def test_parses_ryan_line(self) -> None:
        provider = DuoTTSProvider(_make_voice(), _make_voice())
        result = provider._parse_segments("[RYAN]: Great track!")
        assert result == [("RYAN", "Great track!")]

    def test_parses_emma_line(self) -> None:
        provider = DuoTTSProvider(_make_voice(), _make_voice())
        result = provider._parse_segments("[EMMA]: I love this song.")
        assert result == [("EMMA", "I love this song.")]

    def test_parses_mixed_dialogue(self) -> None:
        provider = DuoTTSProvider(_make_voice(), _make_voice())
        script = "[RYAN]: Hey Emma!\n[EMMA]: Hey Ryan!\n[RYAN]: Let's go."
        result = provider._parse_segments(script)
        assert result == [
            ("RYAN", "Hey Emma!"),
            ("EMMA", "Hey Ryan!"),
            ("RYAN", "Let's go."),
        ]

    def test_labels_uppercased(self) -> None:
        provider = DuoTTSProvider(_make_voice(), _make_voice())
        result = provider._parse_segments("[RYAN]: text")
        assert result[0][0] == "RYAN"


class TestSynthesize:
    @pytest.mark.asyncio
    async def test_plain_text_delegates_to_voice_a(self, tmp_path: Path) -> None:
        voice_a = _make_voice()
        voice_b = _make_voice()
        provider = DuoTTSProvider(voice_a, voice_b)

        await provider.synthesize("Plain text here.", tmp_path / "out.wav")

        voice_a.synthesize.assert_called_once()
        voice_b.synthesize.assert_not_called()

    @pytest.mark.asyncio
    async def test_dialogue_calls_both_voices(self, tmp_path: Path) -> None:
        voice_a = _make_voice()
        voice_b = _make_voice()
        provider = DuoTTSProvider(voice_a, voice_b)

        script = "[RYAN]: Hello!\n[EMMA]: Hi there!"
        result = await provider.synthesize(script, tmp_path / "out.wav")

        assert result is True
        assert voice_a.synthesize.call_count == 1
        assert voice_b.synthesize.call_count == 1

    @pytest.mark.asyncio
    async def test_output_file_created_for_dialogue(self, tmp_path: Path) -> None:
        voice_a = _make_voice()
        voice_b = _make_voice()
        provider = DuoTTSProvider(voice_a, voice_b)

        out = tmp_path / "merged.wav"
        script = "[RYAN]: One.\n[EMMA]: Two."
        await provider.synthesize(script, out)

        assert out.exists()

    @pytest.mark.asyncio
    async def test_returns_false_when_segment_synthesis_fails(
        self, tmp_path: Path
    ) -> None:
        voice_a = AsyncMock(spec=TTSProvider)
        voice_a.audio_suffix = ".wav"
        voice_a.synthesize.return_value = False  # fail

        voice_b = _make_voice()
        provider = DuoTTSProvider(voice_a, voice_b)

        result = await provider.synthesize("[RYAN]: Fail.", tmp_path / "out.wav")

        assert result is False


class TestConcatenateWavs:
    def test_raises_on_empty_list(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            DuoTTSProvider._concatenate_wavs([], tmp_path / "out.wav")

    def test_single_source_copies_correctly(self, tmp_path: Path) -> None:
        src = tmp_path / "a.wav"
        _write_silent_wav(src, frames=800)
        dest = tmp_path / "out.wav"

        DuoTTSProvider._concatenate_wavs([src], dest)

        assert dest.exists()
        with wave.open(str(dest), "rb") as wf:
            assert wf.getnframes() == 800

    def test_two_sources_frame_count_sums(self, tmp_path: Path) -> None:
        src_a = tmp_path / "a.wav"
        src_b = tmp_path / "b.wav"
        _write_silent_wav(src_a, frames=800)
        _write_silent_wav(src_b, frames=400)
        dest = tmp_path / "out.wav"

        DuoTTSProvider._concatenate_wavs([src_a, src_b], dest)

        with wave.open(str(dest), "rb") as wf:
            assert wf.getnframes() == 1200


class TestEstimateDuration:
    @pytest.mark.asyncio
    async def test_plain_text_delegates_to_voice_a(self) -> None:
        voice_a = _make_voice(duration=5.0)
        voice_b = _make_voice(duration=3.0)
        provider = DuoTTSProvider(voice_a, voice_b)

        duration = await provider.estimate_duration("Plain text.")

        assert duration == pytest.approx(5.0)
        voice_a.estimate_duration.assert_called_once()
        voice_b.estimate_duration.assert_not_called()

    @pytest.mark.asyncio
    async def test_dialogue_sums_per_segment(self) -> None:
        voice_a = _make_voice(duration=2.0)
        voice_b = _make_voice(duration=3.0)
        provider = DuoTTSProvider(voice_a, voice_b)

        duration = await provider.estimate_duration("[RYAN]: A.\n[EMMA]: B.")

        assert duration == pytest.approx(5.0)
