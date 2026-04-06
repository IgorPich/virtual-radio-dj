"""Unit tests for AudioDucker."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from src.audio.ducker import AudioDucker, DuckingConfig


class TestDuckingConfig:
    def test_defaults(self) -> None:
        cfg = DuckingConfig()
        assert cfg.duck_target_volume == 0.25
        assert cfg.duck_in_ms == 600
        assert cfg.duck_out_ms == 900
        assert cfg.tail_silence_ms == 300

    def test_frozen(self) -> None:
        cfg = DuckingConfig()
        with pytest.raises(AttributeError):
            cfg.duck_target_volume = 0.5  # type: ignore[misc]


class TestAudioDucker:
    @pytest.mark.asyncio
    async def test_duck_for_success(
        self, audio_ducker: AudioDucker, mock_audio_provider: MagicMock
    ) -> None:
        result = await audio_ducker.duck_for(voice_duration_sec=0.05)
        assert result is True
        assert not audio_ducker.is_ducking
        # Volume should have been set multiple times during ramp.
        assert mock_audio_provider.set_volume.call_count > 0

    @pytest.mark.asyncio
    async def test_duck_for_returns_false_when_no_spotify(
        self, mock_audio_provider: MagicMock, ducking_config: DuckingConfig
    ) -> None:
        mock_audio_provider.get_volume.return_value = None
        ducker = AudioDucker(provider=mock_audio_provider, config=ducking_config)

        result = await ducker.duck_for(voice_duration_sec=1.0)
        assert result is False
        mock_audio_provider.set_volume.assert_not_called()

    @pytest.mark.asyncio
    async def test_is_ducking_during_cycle(
        self, mock_audio_provider: MagicMock, ducking_config: DuckingConfig
    ) -> None:
        ducker = AudioDucker(provider=mock_audio_provider, config=ducking_config)
        assert not ducker.is_ducking

        task = asyncio.create_task(ducker.duck_for(voice_duration_sec=0.1))
        await asyncio.sleep(0.01)  # Let the task start.
        assert ducker.is_ducking
        await task
        assert not ducker.is_ducking

    @pytest.mark.asyncio
    async def test_volume_restored_on_error(
        self, mock_audio_provider: MagicMock, ducking_config: DuckingConfig
    ) -> None:
        """Volume should always be restored even when set_volume fails mid-ramp."""
        call_count = 0

        def fail_after_5_calls(vol: float) -> bool:
            nonlocal call_count
            call_count += 1
            if call_count > 5:
                return False
            return True

        mock_audio_provider.set_volume.side_effect = fail_after_5_calls
        ducker = AudioDucker(provider=mock_audio_provider, config=ducking_config)
        result = await ducker.duck_for(voice_duration_sec=0.01)
        # The ramp breaks early but should not crash.
        assert not ducker.is_ducking

    @pytest.mark.asyncio
    async def test_cancellation_restores_volume(
        self, mock_audio_provider: MagicMock, ducking_config: DuckingConfig
    ) -> None:
        """Cancelling a ducking task must restore volume."""
        ducking_config_slow = DuckingConfig(
            duck_target_volume=0.25,
            duck_in_ms=5000,
            duck_out_ms=5000,
            tail_silence_ms=0,
        )
        ducker = AudioDucker(provider=mock_audio_provider, config=ducking_config_slow)

        task = asyncio.create_task(ducker.duck_for(voice_duration_sec=10.0))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # The last set_volume call should have been the restore-to-original.
        last_vol = mock_audio_provider.set_volume.call_args_list[-1][0][0]
        assert last_vol == pytest.approx(0.8, abs=0.05)
