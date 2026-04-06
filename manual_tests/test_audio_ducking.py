"""
Manual test: verify pycaw can find and control Spotify audio volume.

Requirements:
  - Windows
  - Spotify desktop app running and playing music
  - Speaker/headphones connected

Run:
  python -m pytest manual_tests/test_audio_ducking.py -v -s
"""

from __future__ import annotations

import asyncio
import time

import pytest

from src.audio.ducker import AudioDucker, DuckingConfig
from src.audio.windows_provider import WindowsAudioProvider


@pytest.mark.manual
class TestRealAudioDucking:
    def test_can_find_spotify_session(self) -> None:
        provider = WindowsAudioProvider(process_name="Spotify.exe")
        vol = provider.get_volume()
        assert vol is not None, (
            "Spotify audio session not found. "
            "Make sure Spotify is running and playing music."
        )
        print(f"Current Spotify volume: {vol:.2f}")

    def test_set_volume_round_trip(self) -> None:
        provider = WindowsAudioProvider(process_name="Spotify.exe")
        original = provider.get_volume()
        assert original is not None

        assert provider.set_volume(0.3)
        time.sleep(0.5)
        current = provider.get_volume()
        assert current is not None
        assert abs(current - 0.3) < 0.05

        # Restore.
        assert provider.set_volume(original)

    @pytest.mark.asyncio
    async def test_full_duck_cycle(self) -> None:
        """Audible test: music should fade down, hold 2s, fade back up."""
        provider = WindowsAudioProvider(process_name="Spotify.exe")
        original = provider.get_volume()
        assert original is not None, "Spotify not found."

        config = DuckingConfig(
            duck_target_volume=0.2,
            duck_in_ms=800,
            duck_out_ms=1000,
            tail_silence_ms=200,
        )
        ducker = AudioDucker(provider=provider, config=config)

        print("Starting duck cycle — listen for volume change…")
        result = await ducker.duck_for(voice_duration_sec=2.0)
        assert result is True

        restored = provider.get_volume()
        assert restored is not None
        assert abs(restored - original) < 0.05, (
            f"Volume not restored: expected {original:.2f}, got {restored:.2f}"
        )
        print("Duck cycle complete — volume restored.")
