"""Extended orchestrator tests — error branches and edge cases."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import AlreadyRunningError
from src.core.orchestrator import RadioDJOrchestrator
from src.core.state_manager import DJState
from src.llm.trivia_generator import TriviaGenerator
from src.spotify.models import PlaybackState, Track


@pytest.fixture()
def orchestrator(
    mock_spotify_poller: MagicMock,
    audio_ducker,
    mock_ollama_client: AsyncMock,
    mock_tts_provider: AsyncMock,
) -> RadioDJOrchestrator:
    trivia = TriviaGenerator(client=mock_ollama_client)
    with patch("src.core.orchestrator.pygame"):
        orch = RadioDJOrchestrator(
            poller=mock_spotify_poller,
            ducker=audio_ducker,
            trivia_generator=trivia,
            tts_provider=mock_tts_provider,
            trigger_before_end_sec=20.0,
        )
    return orch


class TestOrchestratorStartStop:
    @pytest.mark.asyncio
    async def test_start_raises_if_already_running(
        self, orchestrator: RadioDJOrchestrator
    ) -> None:
        orchestrator._running = True
        with pytest.raises(AlreadyRunningError):
            await orchestrator.start()

    @pytest.mark.asyncio
    async def test_stop_cancels_interrupt_task(
        self, orchestrator: RadioDJOrchestrator
    ) -> None:
        orchestrator._running = True

        async def long_running() -> None:
            await asyncio.sleep(100)

        orchestrator._interrupt_task = asyncio.create_task(long_running())

        with patch("src.core.orchestrator.pygame") as mock_pg:
            await orchestrator.stop()

        assert not orchestrator._running
        assert orchestrator._interrupt_task.done()

    @pytest.mark.asyncio
    async def test_stop_when_no_interrupt_task(
        self, orchestrator: RadioDJOrchestrator
    ) -> None:
        orchestrator._running = True
        with patch("src.core.orchestrator.pygame"):
            await orchestrator.stop()
        assert not orchestrator._running


class TestRunInterruptErrorBranches:
    @pytest.mark.asyncio
    async def test_unexpected_exception_returns_to_idle(
        self,
        orchestrator: RadioDJOrchestrator,
        sample_track: Track,
        mock_ollama_client: AsyncMock,
    ) -> None:
        """An unexpected exception in the pipeline should be caught and state reset to IDLE."""
        mock_ollama_client.generate.side_effect = RuntimeError("boom")
        await orchestrator._run_interrupt(sample_track)
        assert orchestrator.dj_state == DJState.IDLE

    @pytest.mark.asyncio
    async def test_cancelled_error_re_raises(
        self,
        orchestrator: RadioDJOrchestrator,
        sample_track: Track,
        mock_ollama_client: AsyncMock,
    ) -> None:
        """CancelledError should propagate after cleanup."""
        mock_ollama_client.generate.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await orchestrator._run_interrupt(sample_track)
        assert orchestrator.dj_state == DJState.IDLE

    @pytest.mark.asyncio
    async def test_temp_file_cleaned_up_after_interrupt(
        self,
        orchestrator: RadioDJOrchestrator,
        sample_track: Track,
        mock_tts_provider: AsyncMock,
    ) -> None:
        """The temp audio file should be deleted in the finally block."""
        created_path: Path | None = None

        async def fake_synth(text, path):
            nonlocal created_path
            path.touch()
            created_path = path
            return True

        mock_tts_provider.synthesize.side_effect = fake_synth

        with patch.object(orchestrator, "_play_with_ducking", new_callable=AsyncMock):
            await orchestrator._run_interrupt(sample_track)

        assert created_path is not None
        assert not created_path.exists()


class TestPlayWithDucking:
    @pytest.mark.asyncio
    async def test_play_with_ducking_uses_estimated_on_sound_error(
        self,
        orchestrator: RadioDJOrchestrator,
    ) -> None:
        """When pygame.mixer.Sound raises, fall back to estimated duration."""
        audio_path = Path("fake.mp3")

        with patch("src.core.orchestrator.pygame") as mock_pg:
            mock_pg.mixer.Sound.side_effect = Exception("not a real file")
            mock_pg.mixer.music = MagicMock()
            mock_pg.mixer.music.get_busy.return_value = False

            with patch.object(
                orchestrator._ducker, "duck_for", new_callable=AsyncMock
            ) as mock_duck:
                mock_duck.return_value = True
                await orchestrator._play_with_ducking(audio_path, 2.5)
                mock_duck.assert_awaited_once_with(2.5)


class TestOnPlaybackChangeEdgeCases:
    @pytest.mark.asyncio
    async def test_no_track_in_playing_state(
        self, orchestrator: RadioDJOrchestrator
    ) -> None:
        state = PlaybackState(is_playing=True, current_track=None)
        await orchestrator._on_playback_change(state, None)
        assert orchestrator.dj_state == DJState.IDLE

    @pytest.mark.asyncio
    async def test_track_with_plenty_of_time_no_interrupt(
        self, orchestrator: RadioDJOrchestrator
    ) -> None:
        track = Track(
            id="t2",
            name="Long Song",
            artist="Band",
            duration_ms=300_000,
            progress_ms=10_000,  # 290s remaining — well above threshold
        )
        state = PlaybackState(is_playing=True, current_track=track)
        with patch.object(
            orchestrator, "_maybe_trigger_interrupt", new_callable=AsyncMock
        ) as mock_trigger:
            await orchestrator._on_playback_change(state, None)
            mock_trigger.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_busy_state_prevents_interrupt(
        self, orchestrator: RadioDJOrchestrator, sample_track: Track
    ) -> None:
        orchestrator._state.transition(DJState.SPEAKING)
        await orchestrator._maybe_trigger_interrupt(sample_track)
        # No task should be created because state is busy.
        assert orchestrator._interrupt_task is None
