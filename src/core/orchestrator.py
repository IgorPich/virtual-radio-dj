"""
RadioDJOrchestrator — the central async coordinator.

Wires together the Spotify poller, LLM trivia generator, TTS provider,
audio ducker, and pygame audio playback into a single coherent DJ loop.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pygame

from src.audio.ducker import AudioDucker
from src.core.exceptions import AlreadyRunningError
from src.core.state_manager import DJState, StateManager
from src.llm.trivia_generator import TriviaGenerator
from src.spotify.models import PlaybackState, Track
from src.spotify.poller import SpotifyPoller
from src.tts.provider import TTSProvider
from src.utils.logger import get_logger

_logger = get_logger("core.orchestrator")

# Minimum gap between DJ interrupts (seconds) to prevent spamming.
_COOLDOWN_SEC = 30.0


class RadioDJOrchestrator:
    """
    Coordinates the end-to-end DJ interrupt pipeline.

    The orchestrator is driven by playback-state change events from the
    ``SpotifyPoller``.  When the current track is about to end (within
    ``trigger_before_end_sec`` seconds) it:

    1. Generates trivia about the artist via the LLM (``ANALYZING``).
    2. Estimates TTS duration and synthesises the voice file (``SYNTHESIZING``).
    3. Ducks the music, plays the voice clip, restores the music (``DUCKING_IN``
       → ``SPEAKING`` → ``DUCKING_OUT``).
    4. Returns to ``IDLE``.

    All heavy work is done inside an asyncio ``Task`` so polling continuees
    in parallel.

    Args:
        poller:                Configured :class:`SpotifyPoller`.
        ducker:                Configured :class:`AudioDucker`.
        trivia_generator:      :class:`TriviaGenerator` backed by an LLM.
        tts_provider:          Concrete :class:`TTSProvider` implementation.
        trigger_before_end_sec: How many seconds before end-of-track to
                               fire the DJ interrupt.
    """

    def __init__(
        self,
        poller: SpotifyPoller,
        ducker: AudioDucker,
        trivia_generator: TriviaGenerator,
        tts_provider: TTSProvider,
        trigger_before_end_sec: float = 20.0,
    ) -> None:
        self._poller = poller
        self._ducker = ducker
        self._trivia = trivia_generator
        self._tts = tts_provider
        self._trigger_before_end_sec = trigger_before_end_sec

        self._state = StateManager()
        self._running = False
        self._last_interrupt_time: float = 0.0
        self._current_track: Track | None = None
        self._interrupt_task: asyncio.Task[None] | None = None

        # Initialise pygame mixer once here; it's safe to call repeatedly.
        if not pygame.mixer.get_init():
            pygame.mixer.init()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def dj_state(self) -> DJState:
        """Current high-level DJ state (read-only)."""
        return self._state.state

    @property
    def current_track(self) -> Track | None:
        """The track the orchestrator is currently tracking."""
        return self._current_track

    async def start(self) -> None:
        """
        Start the main orchestration loop.  Blocks until :meth:`stop` is called.

        Raises:
            AlreadyRunningError: If the orchestrator is already running.
        """
        if self._running:
            raise AlreadyRunningError("Orchestrator is already running.")

        self._running = True
        _logger.info("RadioDJ orchestrator started.")
        await self._poller.run(on_state_change=self._on_playback_change)

    async def stop(self) -> None:
        """Stop the orchestrator, cancel any in-progress interrupt, and clean up."""
        self._running = False
        self._poller.stop()

        if self._interrupt_task and not self._interrupt_task.done():
            _logger.info("Cancelling in-progress DJ interrupt.")
            self._interrupt_task.cancel()
            try:
                await self._interrupt_task
            except asyncio.CancelledError:
                pass

        pygame.mixer.quit()
        _logger.info("RadioDJ orchestrator stopped.")

    # ------------------------------------------------------------------ #
    # Spotify state-change callback                                       #
    # ------------------------------------------------------------------ #

    async def _on_playback_change(
        self, new_state: PlaybackState, _previous: PlaybackState | None
    ) -> None:
        """
        Called by the poller every time playback meaningfully changes.

        Decides whether to schedule a DJ interrupt based on time-remaining
        and cooldown guard.
        """
        if not new_state.is_playing or not new_state.current_track:
            _logger.debug("Playback stopped or no track — DJ idle.")
            self._state.transition(DJState.IDLE)
            return

        track = new_state.current_track
        self._current_track = track

        seconds_left = track.remaining_sec
        _logger.debug(
            "Track: '%s' by %s — %.1fs remaining.",
            track.name,
            track.artist,
            seconds_left,
        )

        # Fire the interrupt window.
        if seconds_left <= self._trigger_before_end_sec:
            await self._maybe_trigger_interrupt(track)

    # ------------------------------------------------------------------ #
    # DJ interrupt pipeline                                               #
    # ------------------------------------------------------------------ #

    async def _maybe_trigger_interrupt(self, track: Track) -> None:
        """Gate the interrupt against the busy-state and cooldown guards."""
        if self._state.is_busy:
            return
        cooldown_remaining = _COOLDOWN_SEC - (time.monotonic() - self._last_interrupt_time)
        if cooldown_remaining > 0:
            _logger.debug("DJ on cooldown for another %.1fs.", cooldown_remaining)
            return

        _logger.info(
            "Triggering DJ interrupt for '%s' by %s.", track.name, track.artist
        )
        self._interrupt_task = asyncio.create_task(
            self._run_interrupt(track), name="dj_interrupt"
        )

    async def _run_interrupt(self, track: Track) -> None:
        """
        Execute the full DJ interrupt sequence.

        Handles its own exceptions to ensure the state machine always
        returns to IDLE regardless of failures in individual stages.
        """
        audio_path: Path | None = None
        try:
            # ── Stage 1: Generate trivia ──────────────────────────────
            self._state.transition(DJState.ANALYZING)
            trivia = await self._trivia.generate(
                artist_name=track.artist,
                song_name=track.name,
            )
            if not trivia:
                _logger.warning("No trivia generated — skipping interrupt.")
                return

            # ── Stage 2: Synthesize TTS ──────────────────────────────
            self._state.transition(DJState.SYNTHESIZING)
            estimated_duration = await self._tts.estimate_duration(trivia)

            with tempfile.NamedTemporaryFile(
                suffix=".mp3", delete=False, dir=tempfile.gettempdir()
            ) as tmp:
                audio_path = Path(tmp.name)

            success = await self._tts.synthesize(trivia, audio_path)
            if not success:
                _logger.error("TTS synthesis failed — skipping interrupt.")
                return

            # ── Stage 3: Duck music, play voice, restore ─────────────
            self._state.transition(DJState.DUCKING_IN)
            await self._play_with_ducking(audio_path, estimated_duration)

            self._last_interrupt_time = time.monotonic()

        except asyncio.CancelledError:
            _logger.info("DJ interrupt task cancelled.")
            raise
        except Exception as exc:
            _logger.error("Unexpected error in DJ interrupt: %s", exc, exc_info=True)
        finally:
            self._state.transition(DJState.IDLE)
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except OSError:
                    pass

    async def _play_with_ducking(
        self, audio_path: Path, estimated_duration: float
    ) -> None:
        """
        Duck the music, play the TTS clip via pygame, then unduck.

        Plays the audio file in a thread executor (pygame is threadsafe)
        while the asyncio ducker handles the volume ramp concurrently.
        """
        loop = asyncio.get_running_loop()

        # Load and measure the actual audio duration.
        actual_duration: float = estimated_duration
        try:
            sound = pygame.mixer.Sound(str(audio_path))
            actual_duration = sound.get_length()
        except Exception as exc:
            _logger.warning("Could not load sound via pygame (%s); using estimate.", exc)

        # Run ducking (volume ramp + hold + restore) and playback concurrently.
        self._state.transition(DJState.SPEAKING)
        duck_task = asyncio.create_task(self._ducker.duck_for(actual_duration))

        # Offset playback start to allow the duck-in ramp to begin first.
        duck_in_delay = self._ducker._config.duck_in_ms / 1000.0  # noqa: SLF001
        await asyncio.sleep(duck_in_delay)

        await loop.run_in_executor(None, self._play_audio_sync, audio_path)
        await duck_task

    @staticmethod
    def _play_audio_sync(audio_path: Path) -> None:
        """Blocking pygame playback (runs in executor)."""
        try:
            pygame.mixer.music.load(str(audio_path))
            pygame.mixer.music.play()
            # Poll until playback finishes.
            import time as _time
            while pygame.mixer.music.get_busy():
                _time.sleep(0.05)
        except Exception as exc:
            _logger.error("pygame playback error: %s", exc)
