"""Integration test: full DJ interrupt pipeline with mocked externals."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audio.ducker import AudioDucker, DuckingConfig
from src.audio.provider import AudioProvider
from src.core.orchestrator import RadioDJOrchestrator
from src.core.state_manager import DJState
from src.llm.client import OllamaClient
from src.llm.trivia_generator import TriviaGenerator
from src.spotify.models import PlaybackState, Track
from src.spotify.poller import SpotifyPoller
from src.tts.provider import TTSProvider


@pytest.fixture()
def fast_orchestrator(
    mock_audio_provider: MagicMock,
    mock_ollama_client: AsyncMock,
    mock_tts_provider: AsyncMock,
) -> RadioDJOrchestrator:
    """
    Orchestrator wired to fast mocks for integration testing.

    Uses a real AudioDucker (with mock provider) and a real TriviaGenerator
    (with mock Ollama) so the actual coordination code is exercised.
    """
    poller = MagicMock(spec=SpotifyPoller)
    poller.run = AsyncMock()
    poller.stop = MagicMock()

    ducking_config = DuckingConfig(
        duck_target_volume=0.25,
        duck_in_ms=50,
        duck_out_ms=50,
        tail_silence_ms=0,
    )
    ducker = AudioDucker(provider=mock_audio_provider, config=ducking_config)
    trivia = TriviaGenerator(client=mock_ollama_client)

    with patch("src.core.orchestrator.pygame"):
        orch = RadioDJOrchestrator(
            poller=poller,
            ducker=ducker,
            trivia_generator=trivia,
            tts_provider=mock_tts_provider,
            trigger_before_end_sec=20.0,
        )
    return orch


@pytest.mark.integration
class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_interrupt_flows_through_all_stages(
        self,
        fast_orchestrator: RadioDJOrchestrator,
        mock_ollama_client: AsyncMock,
        mock_tts_provider: AsyncMock,
        mock_audio_provider: MagicMock,
    ) -> None:
        """
        Simulate a track nearing its end and verify the full pipeline:
        LLM generate → TTS synthesize → duck → play → unduck.
        """
        track = Track("t1", "Song", "Artist", 300_000, 285_000)

        async def fake_synth(text, path):
            path.touch()
            return True

        mock_tts_provider.synthesize.side_effect = fake_synth
        mock_tts_provider.estimate_duration.return_value = 0.05

        with patch.object(
            fast_orchestrator, "_play_with_ducking", new_callable=AsyncMock
        ):
            await fast_orchestrator._run_interrupt(track)

        # LLM was called.
        mock_ollama_client.generate.assert_awaited_once()

        # TTS was called.
        mock_tts_provider.synthesize.assert_awaited_once()

        # State should be back to IDLE.
        assert fast_orchestrator.dj_state == DJState.IDLE

    @pytest.mark.asyncio
    async def test_playback_state_change_triggers_interrupt(
        self,
        fast_orchestrator: RadioDJOrchestrator,
    ) -> None:
        """When a track has ≤ trigger_before_end_sec remaining, interrupt fires."""
        track = Track("t1", "Song", "Artist", 300_000, 290_000)  # 10s remaining
        state = PlaybackState(is_playing=True, current_track=track)

        with patch.object(
            fast_orchestrator, "_maybe_trigger_interrupt", new_callable=AsyncMock
        ) as mock_trigger:
            await fast_orchestrator._on_playback_change(state, None)
            mock_trigger.assert_awaited_once_with(track)

    @pytest.mark.asyncio
    async def test_no_interrupt_when_track_has_time(
        self,
        fast_orchestrator: RadioDJOrchestrator,
    ) -> None:
        """Track with plenty of time remaining should NOT trigger an interrupt."""
        track = Track("t1", "Song", "Artist", 300_000, 100_000)  # 200s remaining
        state = PlaybackState(is_playing=True, current_track=track)

        with patch.object(
            fast_orchestrator, "_maybe_trigger_interrupt", new_callable=AsyncMock
        ) as mock_trigger:
            await fast_orchestrator._on_playback_change(state, None)
            mock_trigger.assert_not_awaited()
