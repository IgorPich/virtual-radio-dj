"""Unit tests for the Orchestrator state machine and interrupt pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.orchestrator import RadioDJOrchestrator
from src.core.state_manager import DJState, StateManager
from src.spotify.models import PlaybackState, Track


class TestStateManager:
    def test_initial_state_is_idle(self) -> None:
        sm = StateManager()
        assert sm.state == DJState.IDLE

    def test_transition(self) -> None:
        sm = StateManager()
        sm.transition(DJState.ANALYZING)
        assert sm.state == DJState.ANALYZING

    def test_is_busy_when_not_idle(self) -> None:
        sm = StateManager()
        assert not sm.is_busy
        sm.transition(DJState.SPEAKING)
        assert sm.is_busy

    def test_noop_transition_to_same_state(self) -> None:
        sm = StateManager()
        sm.transition(DJState.IDLE)
        assert sm.state == DJState.IDLE


class TestRadioDJOrchestrator:
    @pytest.fixture()
    def orchestrator(
        self,
        mock_spotify_poller: MagicMock,
        audio_ducker,
        mock_ollama_client: AsyncMock,
        mock_tts_provider: AsyncMock,
        mock_spotify_client: MagicMock,
        module_config,
    ) -> RadioDJOrchestrator:
        from src.llm.trivia_generator import TriviaGenerator

        trivia = TriviaGenerator(client=mock_ollama_client)
        with patch("src.core.orchestrator.pygame"):
            orch = RadioDJOrchestrator(
                poller=mock_spotify_poller,
                ducker=audio_ducker,
                trivia_generator=trivia,
                tts_provider=mock_tts_provider,
                spotify_client=mock_spotify_client,
                trigger_before_end_sec=20.0,
                module_config=module_config,
            )
        return orch

    def test_initial_state_is_idle(self, orchestrator: RadioDJOrchestrator) -> None:
        assert orchestrator.dj_state == DJState.IDLE

    def test_current_track_initially_none(self, orchestrator: RadioDJOrchestrator) -> None:
        assert orchestrator.current_track is None

    @pytest.mark.asyncio
    async def test_on_playback_change_sets_current_track(
        self, orchestrator: RadioDJOrchestrator, sample_track: Track
    ) -> None:
        state = PlaybackState(is_playing=True, current_track=sample_track)
        await orchestrator._on_playback_change(state, None)
        assert orchestrator.current_track == sample_track

    @pytest.mark.asyncio
    async def test_on_playback_change_idle_when_not_playing(
        self, orchestrator: RadioDJOrchestrator
    ) -> None:
        state = PlaybackState(is_playing=False, current_track=None)
        await orchestrator._on_playback_change(state, None)
        assert orchestrator.dj_state == DJState.IDLE

    @pytest.mark.asyncio
    async def test_run_prefetch_generates_trivia_and_synthesizes(
        self,
        orchestrator: RadioDJOrchestrator,
        sample_track: Track,
        mock_ollama_client: AsyncMock,
        mock_tts_provider: AsyncMock,
    ) -> None:
        """Prefetch pipeline should call LLM → TTS and cache the audio path."""
        async def fake_synth(text, path):
            path.touch()
            return True

        mock_tts_provider.synthesize.side_effect = fake_synth

        await orchestrator._run_prefetch(sample_track)

        mock_ollama_client.generate.assert_awaited_once()
        mock_tts_provider.synthesize.assert_awaited_once()
        assert orchestrator._prefetched_audio is not None
        assert orchestrator._prefetched_audio.exists()
        assert orchestrator.dj_state == DJState.IDLE
        # cleanup
        if orchestrator._prefetched_audio:
            orchestrator._prefetched_audio.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_run_prefetch_skips_on_empty_trivia(
        self,
        orchestrator: RadioDJOrchestrator,
        sample_track: Track,
        mock_ollama_client: AsyncMock,
        mock_tts_provider: AsyncMock,
    ) -> None:
        mock_ollama_client.generate.return_value = ""
        await orchestrator._run_prefetch(sample_track)

        mock_tts_provider.synthesize.assert_not_awaited()
        assert orchestrator.dj_state == DJState.IDLE

    @pytest.mark.asyncio
    async def test_run_prefetch_skips_on_tts_failure(
        self,
        orchestrator: RadioDJOrchestrator,
        sample_track: Track,
        mock_tts_provider: AsyncMock,
    ) -> None:
        mock_tts_provider.synthesize.return_value = False
        await orchestrator._run_prefetch(sample_track)
        assert orchestrator._prefetched_audio is None
        assert orchestrator.dj_state == DJState.IDLE

    @pytest.mark.asyncio
    async def test_cooldown_prevents_rapid_interrupts(
        self, orchestrator: RadioDJOrchestrator, sample_track: Track
    ) -> None:
        """After one interrupt, the next within cooldown should be skipped."""
        with patch.object(orchestrator, "_run_interrupt", new_callable=AsyncMock) as mock_run:
            # First call should proceed.
            await orchestrator._maybe_trigger_interrupt(sample_track)
            task = orchestrator._interrupt_task
            if task:
                await task

        # Simulate that _run_interrupt updates _last_interrupt_time.
        import time
        orchestrator._last_interrupt_time = time.monotonic()

        with patch.object(orchestrator, "_run_interrupt", new_callable=AsyncMock) as mock_run:
            await orchestrator._maybe_trigger_interrupt(sample_track)
            # Should NOT have been called because of cooldown.
            mock_run.assert_not_awaited()


class TestConfigValidation:
    def test_audio_config_defaults(self) -> None:
        from src.config.schemas import AudioConfig

        cfg = AudioConfig()
        assert cfg.duck_target_volume == 0.25
        assert cfg.spotify_process_name == "Spotify.exe"

    def test_llm_config_defaults(self) -> None:
        from src.config.schemas import LLMConfig

        cfg = LLMConfig()
        assert cfg.model == "mistral"
        assert cfg.endpoint == "http://localhost:11434"

    def test_spotify_config_requires_credentials(self) -> None:
        from pydantic import ValidationError
        from src.config.schemas import SpotifyConfig

        with pytest.raises(ValidationError):
            SpotifyConfig()  # type: ignore[call-arg]
