"""Unit tests for TTS provider abstraction and local gTTS implementation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tts.local_tts import LocalGTTSProvider
from src.tts.elevenlabs_tts import ElevenLabsTTSProvider
from src.tts.exceptions import TTSProviderNotImplementedError, TTSSynthesisError
from src.tts import create_tts_provider
from src.config.schemas import TTSConfig


class TestLocalGTTSProvider:
    @pytest.mark.asyncio
    async def test_synthesize_success(self, tmp_path: Path) -> None:
        provider = LocalGTTSProvider(language="en", slow=False)
        output = tmp_path / "test.mp3"

        with patch.object(provider, "_sync_synthesize") as mock_sync:
            # Simulate gTTS writing a file.
            def fake_synth(text: str, path: Path) -> None:
                Path(path).touch()

            mock_sync.side_effect = fake_synth
            result = await provider.synthesize("Hello world", output)

        assert result is True
        mock_sync.assert_called_once()

    @pytest.mark.asyncio
    async def test_synthesize_raises_on_failure(self, tmp_path: Path) -> None:
        provider = LocalGTTSProvider()
        output = tmp_path / "fail.mp3"

        with patch.object(provider, "_sync_synthesize", side_effect=RuntimeError("boom")):
            with pytest.raises(TTSSynthesisError, match="boom"):
                await provider.synthesize("test text", output)

    @pytest.mark.asyncio
    async def test_estimate_duration_normal(self) -> None:
        provider = LocalGTTSProvider(slow=False)
        dur = await provider.estimate_duration("one two three four five six seven eight nine ten")
        # 10 words at 150 WPM ≈ 4s; * 1.2 safety ≈ 4.8s
        assert 3.0 < dur < 7.0

    @pytest.mark.asyncio
    async def test_estimate_duration_slow(self) -> None:
        provider = LocalGTTSProvider(slow=True)
        text = "one two three four five six seven eight nine ten"
        dur_slow = await provider.estimate_duration(text)

        provider2 = LocalGTTSProvider(slow=False)
        dur_normal = await provider2.estimate_duration(text)

        assert dur_slow > dur_normal


class TestElevenLabsStub:
    @pytest.mark.asyncio
    async def test_synthesize_raises(self, tmp_path: Path) -> None:
        provider = ElevenLabsTTSProvider()
        with pytest.raises(TTSProviderNotImplementedError):
            await provider.synthesize("test", tmp_path / "out.mp3")

    @pytest.mark.asyncio
    async def test_estimate_raises(self) -> None:
        provider = ElevenLabsTTSProvider()
        with pytest.raises(TTSProviderNotImplementedError):
            await provider.estimate_duration("test")


class TestTTSFactory:
    def test_create_local_gtts(self) -> None:
        cfg = TTSConfig(provider="local_gtts", language="en", slow=False)
        provider = create_tts_provider(cfg)
        assert isinstance(provider, LocalGTTSProvider)

    def test_create_elevenlabs(self) -> None:
        cfg = TTSConfig(provider="elevenlabs")
        provider = create_tts_provider(cfg)
        assert isinstance(provider, ElevenLabsTTSProvider)

    def test_create_unknown_raises(self) -> None:
        cfg = TTSConfig(provider="unknown_engine")
        with pytest.raises(ValueError, match="Unknown TTS provider"):
            create_tts_provider(cfg)
