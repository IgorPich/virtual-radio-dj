"""Unit tests for audio exceptions and timing utilities."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from src.audio.exceptions import (
    AudioError,
    ProcessNotFoundError,
    VolumeControlError,
)
from src.utils.timing_utils import timed, words_to_seconds


class TestAudioExceptions:
    def test_audio_error_is_base(self) -> None:
        err = AudioError("generic")
        assert isinstance(err, Exception)
        assert str(err) == "generic"

    def test_process_not_found_error(self) -> None:
        err = ProcessNotFoundError("Spotify.exe")
        assert isinstance(err, AudioError)
        assert err.process_name == "Spotify.exe"
        assert "Spotify.exe" in str(err)

    def test_volume_control_error(self) -> None:
        err = VolumeControlError("set failed")
        assert isinstance(err, AudioError)
        assert str(err) == "set failed"


class TestTimedContextManager:
    def test_timed_prints_elapsed(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            with timed("test_op"):
                _ = sum(range(100))

        output = buf.getvalue()
        assert "[timer] test_op:" in output
        assert "s" in output

    def test_timed_without_label(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            with timed():
                pass

        output = buf.getvalue()
        assert "[timer] :" in output


class TestWordsToSeconds:
    def test_basic_word_count(self) -> None:
        text = "one two three four five six seven"
        result = words_to_seconds(text, wpm=140)
        expected = 7 / (140 / 60.0)
        assert result == pytest.approx(expected)

    def test_empty_text(self) -> None:
        assert words_to_seconds("") == 0.0

    def test_custom_wpm(self) -> None:
        text = "hello world"
        result = words_to_seconds(text, wpm=60)
        assert result == pytest.approx(2.0)
