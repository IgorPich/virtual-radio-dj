"""Extended orchestrator tests — error branches and edge cases."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import AlreadyRunningError
from src.core.orchestrator import RadioDJOrchestrator
from src.core.state_manager import DJState
from src.config.modules import ModuleConfig
from src.llm.trivia_generator import TriviaGenerator
from src.news.fetcher import NewsData
from src.spotify.models import PlaybackState, Track


@pytest.fixture()
def orchestrator(
    mock_spotify_poller: MagicMock,
    audio_ducker,
    mock_ollama_client: AsyncMock,
    mock_tts_provider: AsyncMock,
    mock_spotify_client: MagicMock,
    module_config,
) -> RadioDJOrchestrator:
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
        """An unexpected exception in the prefetch pipeline should be caught and state reset to IDLE."""
        mock_ollama_client.generate.side_effect = RuntimeError("boom")
        await orchestrator._run_prefetch(sample_track)
        assert orchestrator.dj_state == DJState.IDLE

    @pytest.mark.asyncio
    async def test_cancelled_error_re_raises(
        self,
        orchestrator: RadioDJOrchestrator,
        sample_track: Track,
        mock_ollama_client: AsyncMock,
    ) -> None:
        """CancelledError in the prefetch pipeline should propagate after cleanup."""
        mock_ollama_client.generate.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await orchestrator._run_prefetch(sample_track)
        assert orchestrator.dj_state == DJState.IDLE

    @pytest.mark.asyncio
    async def test_temp_file_cleaned_up_after_interrupt(
        self,
        orchestrator: RadioDJOrchestrator,
        sample_track: Track,
        mock_spotify_client: MagicMock,
    ) -> None:
        """The pre-fetched audio file should be deleted in the finally block of _run_interrupt."""
        import tempfile

        # Create a real temp file and pre-load it as the cached audio.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio_path = Path(tmp.name)
        audio_path.touch()
        orchestrator._prefetched_audio = audio_path

        with patch.object(orchestrator, "_play_with_ducking", new_callable=AsyncMock):
            await orchestrator._run_interrupt(sample_track)

        assert not audio_path.exists()


class TestNewsAndFakeCommercials:
    @pytest.mark.asyncio
    async def test_news_bulletin_runs_fake_commercial_after_success(
        self,
        orchestrator: RadioDJOrchestrator,
        mock_ollama_client: AsyncMock,
        mock_tts_provider: AsyncMock,
        mock_spotify_client: MagicMock,
    ) -> None:
        orchestrator._module_config = ModuleConfig(
            top_of_hour_news_enabled=True,
            radio_imaging_enabled=False,
            fake_commercials_enabled=True,
        )
        orchestrator._news_fetcher.fetch = MagicMock(
            return_value=NewsData(
                world="World headline.",
                country="Poland headline.",
                local="Warsaw headline.",
                weather="",
            )
        )
        mock_ollama_client.generate.side_effect = [
            "Here is the news.",
            "Try Panic Yogurt, the breakfast that screams back.",
        ]

        async def fake_synth(_text, path):
            path.touch()
            return True

        mock_tts_provider.synthesize.side_effect = fake_synth

        with patch.object(orchestrator, "_play_with_ducking", new_callable=AsyncMock) as mock_play:
            await orchestrator._run_news_bulletin()

        assert mock_ollama_client.generate.await_count == 2
        assert mock_tts_provider.synthesize.await_count == 2
        assert mock_play.await_count == 2
        assert orchestrator._last_fake_commercial_hour is not None
        mock_spotify_client.pause_playback.assert_called_once()
        mock_spotify_client.resume_playback.assert_called_once()

    @pytest.mark.asyncio
    async def test_fake_commercial_skips_when_disabled(
        self,
        orchestrator: RadioDJOrchestrator,
        mock_ollama_client: AsyncMock,
    ) -> None:
        orchestrator._module_config = ModuleConfig(fake_commercials_enabled=False)

        await orchestrator._run_fake_commercial_if_due(hour=9)

        mock_ollama_client.generate.assert_not_awaited()


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

    @pytest.mark.asyncio
    async def test_play_with_ducking_reveals_and_clears_text_on_audio_events(
        self,
        orchestrator: RadioDJOrchestrator,
    ) -> None:
        audio_path = Path("fake.mp3")

        def fake_play(_path, on_play=None, on_end=None):
            if on_play:
                on_play()
            if on_end:
                on_end()

        with (
            patch.object(orchestrator, "_start_bed", return_value=None),
            patch.object(orchestrator, "_stop_bed"),
            patch.object(orchestrator, "_play_audio_sync", side_effect=fake_play),
            patch.object(orchestrator, "_broadcast_event") as mock_broadcast,
            patch.object(orchestrator._ducker, "duck_for", new_callable=AsyncMock) as mock_duck,
        ):
            mock_duck.return_value = True
            await orchestrator._play_with_ducking(
                audio_path, 1.0, display_text="Hello from the booth."
            )

        mock_broadcast.assert_any_call(
            "monologue", {"text": "Hello from the booth."}
        )
        mock_broadcast.assert_any_call("monologue_clear", {})
        assert orchestrator.last_monologue == ""


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
