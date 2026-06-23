"""Unit tests for TTS provider abstraction and local gTTS implementation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tts.local_tts import LocalGTTSProvider
from src.tts.elevenlabs_tts import ElevenLabsTTSProvider
from src.tts.exceptions import TTSSynthesisError
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


class TestElevenLabsProvider:
    def test_init_raises_without_api_key(self) -> None:
        with pytest.raises(ValueError, match="API key is required"):
            ElevenLabsTTSProvider(api_key="", voice_id="voice_123")

    def test_init_raises_without_voice_id(self) -> None:
        with pytest.raises(ValueError, match="voice ID is required"):
            ElevenLabsTTSProvider(api_key="sk-test", voice_id="")

    def test_init_success(self) -> None:
        provider = ElevenLabsTTSProvider(
            api_key="sk-test", voice_id="voice_123", model="eleven_turbo_v2_5"
        )
        assert provider is not None

    @pytest.mark.asyncio
    async def test_estimate_duration(self) -> None:
        provider = ElevenLabsTTSProvider(api_key="sk-test", voice_id="v1")
        dur = await provider.estimate_duration(
            "one two three four five six seven eight nine ten"
        )
        assert 3.0 < dur < 7.0


class TestTTSFactory:
    def test_create_local_gtts(self) -> None:
        cfg = TTSConfig(provider="local_gtts", language="en", slow=False)
        provider = create_tts_provider(cfg)
        assert isinstance(provider, LocalGTTSProvider)

    def test_create_elevenlabs(self) -> None:
        cfg = TTSConfig(
            provider="elevenlabs",
            elevenlabs_api_key="sk-test",
            elevenlabs_voice_id="voice_123",
        )
        provider = create_tts_provider(cfg)
        assert isinstance(provider, ElevenLabsTTSProvider)

    def test_create_unknown_raises(self) -> None:
        cfg = TTSConfig(provider="unknown_engine")
        with pytest.raises(ValueError, match="Unknown TTS provider"):
            create_tts_provider(cfg)

    def test_create_piper(self, tmp_path: Path) -> None:
        model_file = tmp_path / "en_US-ryan-high.onnx"
        exe_file = tmp_path / "piper.exe"
        model_file.touch()
        exe_file.touch()
        cfg = TTSConfig(
            provider="piper",
            piper_model_path=str(model_file),
            piper_exe_path=str(exe_file),
        )
        provider = create_tts_provider(cfg)
        from src.tts.piper_tts import PiperTTSProvider

        assert isinstance(provider, PiperTTSProvider)


class TestPiperTTSProvider:
    """Tests for the subprocess-based Piper TTS provider."""

    def _make_provider(self, tmp_path: Path):
        from src.tts.piper_tts import PiperTTSProvider

        model = tmp_path / "en_US-ryan-high.onnx"
        exe = tmp_path / "piper.exe"
        model.touch()
        exe.touch()
        return PiperTTSProvider(
            model_path=str(model), exe_path=str(exe), speaker_id=None
        )

    def test_init_raises_without_model_path(self, tmp_path: Path) -> None:
        # No staged piper_tts/ in this context — should raise ValueError.
        from src.tts.piper_tts import PiperTTSProvider, _STAGE_DIR

        with patch("src.tts.piper_tts._STAGE_DIR", tmp_path / "nonexistent"):
            with pytest.raises(ValueError, match="model path is required"):
                PiperTTSProvider(model_path="", exe_path="")

    def test_init_raises_with_missing_model_file(self, tmp_path: Path) -> None:
        from src.tts.piper_tts import PiperTTSProvider

        with pytest.raises(FileNotFoundError, match="Piper model not found"):
            PiperTTSProvider(
                model_path=str(tmp_path / "missing.onnx"),
                exe_path=str(tmp_path / "piper.exe"),
            )

    def test_init_raises_with_missing_exe(self, tmp_path: Path) -> None:
        from src.tts.piper_tts import PiperTTSProvider

        model = tmp_path / "en_US-ryan-high.onnx"
        model.touch()
        with patch("src.tts.piper_tts._STAGE_DIR", tmp_path / "nonexistent"):
            with pytest.raises(FileNotFoundError, match="piper.exe not found"):
                PiperTTSProvider(model_path=str(model), exe_path="")

    def test_init_success(self, tmp_path: Path) -> None:
        provider = self._make_provider(tmp_path)
        assert provider.audio_suffix == ".wav"

    def test_autodiscover_exe_from_model_directory(self, tmp_path: Path) -> None:
        """piper.exe next to the model is auto-discovered when exe_path=''.."""
        from src.tts.piper_tts import PiperTTSProvider

        model = tmp_path / "en_US-ryan-high.onnx"
        exe = tmp_path / "piper.exe"
        model.touch()
        exe.touch()
        # Pass exe_path="" — should discover from model's directory.
        with patch("src.tts.piper_tts._STAGE_DIR", tmp_path / "nonexistent"):
            provider = PiperTTSProvider(model_path=str(model), exe_path="")
        assert provider._exe_path == exe

    @pytest.mark.asyncio
    async def test_synthesize_success(self, tmp_path: Path) -> None:
        provider = self._make_provider(tmp_path)
        output = tmp_path / "out.wav"

        async def fake_run_piper(text, path):
            path.touch()

        with patch.object(provider, "_run_piper", side_effect=fake_run_piper):
            result = await provider.synthesize("Hello world", output)

        assert result is True

    @pytest.mark.asyncio
    async def test_synthesize_raises_on_failure(self, tmp_path: Path) -> None:
        provider = self._make_provider(tmp_path)
        output = tmp_path / "fail.wav"

        async def boom(text, path):
            raise RuntimeError("piper crash")

        with patch.object(provider, "_run_piper", side_effect=boom):
            with pytest.raises(TTSSynthesisError, match="piper crash"):
                await provider.synthesize("test", output)

    @pytest.mark.asyncio
    async def test_estimate_duration(self, tmp_path: Path) -> None:
        provider = self._make_provider(tmp_path)
        dur = await provider.estimate_duration(
            "one two three four five six seven eight nine ten"
        )
        # 10 words at 170 WPM ≈ 3.5s * 1.2 safety ≈ 4.2s
        assert 2.5 < dur < 7.0

    @pytest.mark.asyncio
    async def test_speaker_id_passed_to_command(self, tmp_path: Path) -> None:
        from src.tts.piper_tts import PiperTTSProvider

        model = tmp_path / "en_US-ryan-high.onnx"
        exe = tmp_path / "piper.exe"
        model.touch()
        exe.touch()
        provider = PiperTTSProvider(
            model_path=str(model), exe_path=str(exe), speaker_id=2
        )
        assert provider._speaker_id == 2
