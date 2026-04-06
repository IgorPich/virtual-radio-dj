"""
Manual test: verify gTTS can synthesize speech and pygame can play it.

Requirements:
  - Internet connection (gTTS uses Google Translate backend)
  - Speakers/headphones

Run:
  python -m pytest manual_tests/test_tts_generation.py -v -s
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

import pygame
import pytest

from src.tts.local_tts import LocalGTTSProvider


@pytest.mark.manual
class TestRealTTS:
    @pytest.mark.asyncio
    async def test_synthesize_and_play(self) -> None:
        provider = LocalGTTSProvider(language="en", slow=False)

        with TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dj_test.mp3"
            text = (
                "Hey music lovers, did you know that Freddie Mercury "
                "could sing across four octaves? Absolutely legendary."
            )

            print("Synthesizing…")
            ok = await provider.synthesize(text, output)
            assert ok, "TTS synthesis failed."
            assert output.exists(), "Output file was not created."
            print(f"Wrote {output.stat().st_size} bytes → {output}")

            est = await provider.estimate_duration(text)
            print(f"Estimated duration: {est:.1f}s")

            # Play it.
            print("Playing audio…")
            pygame.mixer.init()
            pygame.mixer.music.load(str(output))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
            pygame.mixer.quit()
            print("Done.")
