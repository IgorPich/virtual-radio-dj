"""
RadioDJOrchestrator — the central async coordinator.

Wires together the Spotify poller, LLM trivia generator, TTS provider,
audio ducker, and pygame audio playback into a single coherent DJ loop.
"""

from __future__ import annotations

import asyncio
import json
import queue
import random
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pygame

from src.audio.ducker import AudioDucker
from src.config.modules import ModuleConfig, load_module_config
from src.config.schemas import DJConfig
from src.core.exceptions import AlreadyRunningError
from src.core.state_manager import DJState, StateManager
from src.llm.trivia_generator import TriviaGenerator, is_duo_time
from src.news.fetcher import NewsArticle, RssNewsFetcher
from src.spotify.client import SpotifyClient
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
    ``SpotifyPoller``.  When the current track is due for a DJ break it
    pre-generates the script/audio, then enters the break when fresh Spotify
    progress shows the track is within ``trigger_before_end_sec`` seconds
    of ending.

    1. Generates a DJ monologue about the artist via the LLM (``ANALYZING``).
    2. Estimates TTS duration and synthesises the voice file (``SYNTHESIZING``).
    3. Ducks the music and speaks over the outro (``DUCKING_IN``
       → ``SPEAKING`` → ``DUCKING_OUT``).
    4. Returns to ``IDLE``.

    The DJ does **not** speak after every track — it waits for a randomised
    number of songs (``dj_config.song_interval_min`` to
    ``dj_config.song_interval_max``) before triggering.

    When a track is skipped:
    - **Early skip** (listened < ``dj_config.skip_grace_period_sec``):
      DJ is suppressed (browsing behaviour).
    - **Late skip** (listened ≥ grace period): DJ triggers immediately
      if the song counter threshold is met.
    """

    def __init__(
        self,
        poller: SpotifyPoller,
        ducker: AudioDucker,
        trivia_generator: TriviaGenerator,
        tts_provider: TTSProvider,
        spotify_client: SpotifyClient,
        trigger_before_end_sec: float = 20.0,
        dj_config: DJConfig | None = None,
        module_config: ModuleConfig | None = None,
        tts_cohost: TTSProvider | None = None,
        cohost_name: str = "Emma",
    ) -> None:
        self._poller = poller
        self._ducker = ducker
        self._trivia = trivia_generator
        self._tts = tts_provider
        self._tts_cohost = tts_cohost
        self._spotify_client = spotify_client
        self._trigger_before_end_sec = trigger_before_end_sec
        self._dj_config = dj_config or DJConfig()
        self._module_config = module_config or load_module_config()
        self._cohost_name = cohost_name

        self._state = StateManager()
        self._running = False
        self._last_interrupt_time: float = 0.0
        self._current_track: Track | None = None
        self._previous_track: Track | None = None
        self._interrupt_task: asyncio.Task[None] | None = None
        self._scheduled_trigger_task: asyncio.Task[None] | None = None

        # ── DJ frequency ──────────────────────────────────────────────
        self._songs_since_last_dj: int = 0
        self._next_dj_at: int = self._roll_next_interval()

        # ── Skip detection ────────────────────────────────────────────
        self._track_first_seen: float = 0.0

        # ── Monologue + event broadcasting ────────────────────────────
        self._last_monologue: str = ""
        self._next_track: Track | None = None
        self._sse_clients: list[queue.Queue[str]] = []

        # ── Prefetch pipeline ──────────────────────────────────────────
        # Populated during the prefetch phase; consumed during playback control.
        self._prefetched_audio: Path | None = None
        self._prefetched_monologue: str = ""
        self._prefetch_task: asyncio.Task[None] | None = None
        self._playback_task: asyncio.Task[None] | None = None
        # ── News scheduler ─────────────────────────────────────────
        self._news_fetcher = RssNewsFetcher()
        self._news_task: asyncio.Task[None] | None = None
        self._last_fake_commercial_hour: int | None = None
        self._latest_news_articles: list[NewsArticle] = []
        self._latest_news_updated_at: str | None = None
        self._latest_news_hour: int | None = None
        # Initialise pygame mixer once here; it's safe to call repeatedly.
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        # Wire state transitions to SSE broadcast.
        self._state.on_transition(self._on_state_transition)

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _roll_next_interval(self) -> int:
        """Pick a random song count target for the next DJ interrupt."""
        lo = self._dj_config.song_interval_min
        hi = self._dj_config.song_interval_max
        target = random.randint(lo, max(lo, hi))
        _logger.debug("Next DJ interrupt after %d songs.", target)
        return target

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

    @property
    def last_monologue(self) -> str:
        """The most recent DJ monologue text."""
        return self._last_monologue

    @property
    def next_track(self) -> Track | None:
        """The next queued track as last fetched from Spotify."""
        return self._next_track

    @property
    def runtime_settings(self) -> dict:
        """Return live settings exposed to the web UI."""
        return {
            "dj_enabled": self._module_config.dj_enabled,
            "top_of_hour_news_enabled": self._module_config.top_of_hour_news_enabled,
            "duo_mode_enabled": self._module_config.duo_mode_enabled,
            "radio_imaging_enabled": self._module_config.radio_imaging_enabled,
            "fake_commercials_enabled": self._module_config.fake_commercials_enabled,
            "trigger_before_end_sec": self._trigger_before_end_sec,
        }

    def update_runtime_settings(self, updates: dict) -> dict:
        """
        Apply live settings from the UI and return the updated settings.

        These changes are intentionally in-memory so they affect the current
        broadcast immediately without rewriting deployment configuration files.
        """
        module_fields = set(self._module_config.model_fields)
        module_updates = {
            key: value
            for key, value in updates.items()
            if key in module_fields
        }
        if module_updates:
            self._module_config = self._module_config.model_copy(update=module_updates)

        if "trigger_before_end_sec" in updates:
            value = float(updates["trigger_before_end_sec"])
            if value < 5.0:
                raise ValueError("trigger_before_end_sec must be at least 5 seconds.")
            self._trigger_before_end_sec = value

        if not self._module_config.dj_enabled:
            self._discard_prefetched_audio()
            for task in (self._prefetch_task, self._playback_task):
                if task and not task.done():
                    task.cancel()

        return self.runtime_settings

    def latest_news_links(self) -> dict:
        """Return cached top-of-hour article links for the web UI."""
        return {
            "updated_at": self._latest_news_updated_at,
            "hour": f"{self._latest_news_hour:02d}:00"
            if self._latest_news_hour is not None
            else None,
            "articles": [
                {
                    "title": article.title,
                    "url": article.url,
                    "source": article.source,
                    "category": article.category,
                }
                for article in self._latest_news_articles
            ],
        }

    def refresh_news_links(self) -> dict:
        """Fetch fresh RSS article links without changing the spoken bulletin."""
        news = self._news_fetcher.fetch()
        self._cache_news_links(news.articles, datetime.now())
        return self.latest_news_links()

    # ── SSE event fan-out ─────────────────────────────────────────────

    def register_sse_client(self) -> queue.Queue[str]:
        """Register a new SSE client and return its event queue."""
        q: queue.Queue[str] = queue.Queue(maxsize=64)
        self._sse_clients.append(q)
        _logger.debug("SSE client registered (%d total).", len(self._sse_clients))
        return q

    def unregister_sse_client(self, q: queue.Queue[str]) -> None:
        """Remove an SSE client queue."""
        try:
            self._sse_clients.remove(q)
        except ValueError:
            pass
        _logger.debug("SSE client removed (%d remaining).", len(self._sse_clients))

    def _broadcast_event(self, event: str, data: dict) -> None:
        """Push a server-sent event to all registered SSE clients."""
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        dead: list[queue.Queue[str]] = []
        for q in self._sse_clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            try:
                self._sse_clients.remove(q)
            except ValueError:
                pass

    def _on_state_transition(self, _old: DJState, new: DJState) -> None:
        """Callback from StateManager — broadcast state change via SSE."""
        self._broadcast_event("state", {"dj_state": new.name})

    def _broadcast_track(self, track: Track | None) -> None:
        """Broadcast current track info to SSE clients."""
        if track:
            data = {
                "name": track.name,
                "artist": track.artist,
                "album_art_url": track.album_art_url,
                "duration_ms": track.duration_ms,
                "progress_ms": track.progress_ms,
            }
        else:
            data = None  # type: ignore[assignment]
        self._broadcast_event("track", {"current_track": data})

    def _cache_news_links(
        self, articles: list[NewsArticle], timestamp: datetime, hour: int | None = None
    ) -> None:
        """Store article links from the latest news fetch for the UI."""
        self._latest_news_articles = articles
        self._latest_news_updated_at = timestamp.isoformat()
        self._latest_news_hour = timestamp.hour if hour is None else hour

    async def _refresh_next_track(self) -> None:
        """Fetch the next queued track from Spotify and broadcast it via SSE."""
        loop = asyncio.get_running_loop()
        next_track = await loop.run_in_executor(
            None, self._spotify_client.get_next_in_queue
        )
        self._next_track = next_track
        self._broadcast_event(
            "next_track",
            {
                "next_track": {
                    "name": next_track.name,
                    "artist": next_track.artist,
                    "album_art_url": next_track.album_art_url,
                }
                if next_track
                else None
            },
        )

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
        self._start_news_scheduler()
        await self._poller.run(on_state_change=self._on_playback_change)

    async def stop(self) -> None:
        """Stop the orchestrator, cancel any in-progress tasks, and clean up."""
        self._running = False
        self._poller.stop()

        for task in (
            self._scheduled_trigger_task,
            self._prefetch_task,
            self._playback_task,
            self._interrupt_task,
            self._news_task,
        ):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._discard_prefetched_audio()
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

        Handles three scenarios:
        1. **Track change (skip or natural end)** — classify as early/late
           skip or natural end, update the song counter, and decide whether
           to trigger the DJ.
        2. **Track within trigger window** — schedule or fire the DJ.
        3. **Playback stopped** — go idle.
        """
        # Cancel any stale scheduled trigger on every state change.
        if self._scheduled_trigger_task and not self._scheduled_trigger_task.done():
            self._scheduled_trigger_task.cancel()
            self._scheduled_trigger_task = None

        if not new_state.is_playing or not new_state.current_track:
            _logger.debug("Playback stopped or no track — DJ idle.")
            self._state.transition(DJState.IDLE)
            return

        track = new_state.current_track
        is_new_track = (
            self._current_track is None
            or track.id != self._current_track.id
        )

        if is_new_track:
            await self._handle_track_change(track)
        else:
            # Same track, check if we should schedule the end-of-track trigger.
            self._schedule_end_trigger(track)

    async def _handle_track_change(self, new_track: Track) -> None:
        """Process a track transition — classify skip type, update counters."""
        old_track = self._current_track
        listened_sec = time.monotonic() - self._track_first_seen if old_track else 0.0
        grace = self._dj_config.skip_grace_period_sec

        # Cancel any in-flight prefetch or playback tasks from the previous track.
        for task in (self._prefetch_task, self._playback_task):
            if task and not task.done():
                task.cancel()
        self._prefetch_task = None
        self._playback_task = None
        self._discard_prefetched_audio()

        # Update tracking state.
        self._previous_track = old_track
        self._current_track = new_track
        self._track_first_seen = time.monotonic()
        self._broadcast_track(new_track)
        asyncio.create_task(self._refresh_next_track())

        if old_track is None:
            # First track observed — just start tracking.
            _logger.debug(
                "First track observed: '%s' by %s.",
                new_track.name, new_track.artist,
            )
            self._schedule_end_trigger(new_track)
            return

        self._songs_since_last_dj += 1
        _logger.debug(
            "Track changed: '%s' → '%s' (listened %.1fs, counter %d/%d).",
            old_track.name, new_track.name, listened_sec,
            self._songs_since_last_dj, self._next_dj_at,
        )

        if listened_sec < grace:
            # ── Early skip: user is browsing — suppress DJ ────────────
            _logger.debug(
                "Early skip detected (%.1fs < %.1fs grace) — suppressing DJ.",
                listened_sec, grace,
            )
        else:
            _logger.debug(
                "Late skip detected (%.1fs ≥ %.1fs grace) — scheduling end trigger.",
                listened_sec, grace,
            )
        self._schedule_end_trigger(new_track)

    # Minimum progress (ms) a track must have before the immediate-fire branch
    # of _schedule_end_trigger activates.  Guards against Spotify API lag that
    # briefly reports a freshly-started track as nearly done (progress_ms ≈ 0).
    _MIN_PROGRESS_MS_FOR_TRIGGER: int = 30_000

    def _schedule_end_trigger(self, track: Track) -> None:
        """Prefetch if a break is due, then schedule talk-over at the configured gate."""
        seconds_left = track.remaining_sec
        _logger.debug(
            "Track: '%s' by %s — %.1fs remaining.",
            track.name, track.artist, seconds_left,
        )

        if not self._module_config.dj_enabled:
            _logger.debug("DJ disabled by runtime settings — no interrupt scheduled.")
            return

        if self._songs_since_last_dj < self._next_dj_at:
            _logger.debug(
                "DJ gated by song counter (%d/%d).",
                self._songs_since_last_dj, self._next_dj_at,
            )
            return

        # Guard against Spotify briefly reporting a freshly-started track as
        # almost finished.
        if seconds_left <= self._trigger_before_end_sec and track.progress_ms < self._MIN_PROGRESS_MS_FOR_TRIGGER:
            _logger.debug(
                "Track just started (progress %.1fs) — deferring trigger.",
                track.progress_ms / 1000.0,
            )
            return

        if self._prefetched_audio is None and (
            self._prefetch_task is None or self._prefetch_task.done()
        ):
            self._prefetch_task = asyncio.create_task(
                self._run_prefetch(track), name="dj_prefetch"
            )

        if self._playback_task and not self._playback_task.done():
            return

        if seconds_left > self._trigger_before_end_sec:
            playback_delay = seconds_left - self._trigger_before_end_sec
            _logger.debug(
                "Scheduling playback control in %.1fs for '%s'.", playback_delay, track.name
            )
            self._playback_task = asyncio.create_task(
                self._delayed_playback_control(track, playback_delay),
                name="dj_playback_trigger",
            )
        else:
            _logger.debug(
                "Inside playback control window (%.1fs left) — triggering now.", seconds_left
            )
            self._playback_task = asyncio.create_task(
                self._maybe_trigger_interrupt(track), name="dj_playback_now"
            )

    # ------------------------------------------------------------------ #
    # DJ interrupt pipeline                                               #
    # ------------------------------------------------------------------ #

    async def _delayed_prefetch(self, track: Track, delay: float) -> None:
        """Sleep until the prefetch window, then kick off LLM+TTS generation."""
        try:
            await asyncio.sleep(delay)
            self._prefetch_task = asyncio.create_task(
                self._run_prefetch(track), name="dj_prefetch"
            )
        except asyncio.CancelledError:
            _logger.debug("Prefetch trigger cancelled for '%s'.", track.name)

    async def _delayed_playback_control(self, track: Track, delay: float) -> None:
        """
        Poll Spotify until the configured trigger gate, then fire the interrupt.

        Rather than trusting a single long ``asyncio.sleep`` (which drifts when
        the user pauses/scrubs), we:
          1. Sleep a coarse initial delay to get close to the window without
             hammering the API.
          2. Poll every 1.5 s, reading live ``remaining_sec`` from the poller's
             last known state, until we are inside the 10-second gate.
          3. Only then hand off to ``_maybe_trigger_interrupt``.
        """
        poll_interval_sec = 1.0
        gate_ms = self._trigger_before_end_sec * 1000.0
        coarse_buffer_sec = max(5.0, min(15.0, self._trigger_before_end_sec))
        try:
            # ── Stage 1: coarse sleep to save API calls ───────────────
            coarse_sleep = max(0.0, delay - coarse_buffer_sec)
            if coarse_sleep > 0:
                _logger.debug(
                    "Playback control: coarse sleep %.1fs for '%s'.",
                    coarse_sleep, track.name,
                )
                await asyncio.sleep(coarse_sleep)

            # ── Stage 2: tight polling loop ───────────────────────────
            _logger.debug(
                "Playback control: entering polling loop for '%s'.", track.name
            )
            while True:
                live_track = await self._fetch_fresh_track(track.id)
                if live_track is None or live_track.id != track.id:
                    # Track already changed — abort.
                    _logger.debug(
                        "Playback control: track changed mid-poll — aborting."
                    )
                    return

                self._current_track = live_track
                self._broadcast_track(live_track)
                remaining_ms = live_track.remaining_ms
                _logger.debug(
                    "Playback control poll: '%s' — %.1fs remaining.",
                    live_track.name, remaining_ms / 1000.0,
                )

                if remaining_ms <= gate_ms:
                    break

                await asyncio.sleep(poll_interval_sec)

            await self._maybe_trigger_interrupt(track)

        except asyncio.CancelledError:
            _logger.debug("Playback control trigger cancelled for '%s'.", track.name)

    async def _fetch_fresh_track(self, expected_track_id: str) -> Track | None:
        """Fetch a fresh Spotify playback snapshot for precise progress timing."""
        loop = asyncio.get_running_loop()
        try:
            state = await loop.run_in_executor(None, self._spotify_client.get_playback_state)
        except Exception as exc:
            _logger.warning("Fresh Spotify progress poll failed: %s", exc)
            return self._current_track

        if not state.is_playing or not state.current_track:
            return None
        if state.current_track.id != expected_track_id:
            return state.current_track
        return state.current_track

    async def _maybe_trigger_interrupt(self, track: Track) -> None:
        """Gate the interrupt against the busy-state, song counter, and cooldown."""
        if self._state.is_busy:
            return

        if not self._module_config.dj_enabled:
            _logger.debug("DJ disabled by runtime settings.")
            return

        # ── Song counter gate ─────────────────────────────────────────
        if self._songs_since_last_dj < self._next_dj_at:
            _logger.debug(
                "DJ gated by song counter (%d/%d).",
                self._songs_since_last_dj, self._next_dj_at,
            )
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

    async def _run_prefetch(self, track: Track) -> None:
        """
        Phase 1 — Generate LLM monologue + TTS audio and cache them.

        Runs silently; errors are logged but do not affect playback state.
        If the interrupt is ultimately gated (counter/cooldown), the cached
        files are discarded by _discard_prefetched_audio().
        """
        _logger.info("Prefetching DJ audio for '%s' by %s.", track.name, track.artist)
        loop = asyncio.get_running_loop()
        audio_path: Path | None = None
        try:
            # ── Fetch enrichment data in parallel ─────────────────────
            next_track, artist_info = await asyncio.gather(
                loop.run_in_executor(None, self._spotify_client.get_next_in_queue),
                loop.run_in_executor(None, self._spotify_client.get_artist_info, track.artist),
            )

            # Update the SSE "up next" panel while we're at it.
            self._next_track = next_track
            self._broadcast_event(
                "next_track",
                {
                    "next_track": {
                        "name": next_track.name,
                        "artist": next_track.artist,
                        "album_art_url": next_track.album_art_url,
                    }
                    if next_track
                    else None
                },
            )

            # ── Generate monologue ─────────────────────────────────────
            self._state.transition(DJState.ANALYZING)
            trivia = await self._trivia.generate(
                artist_name=track.artist,
                song_name=track.name,
                previous_track=self._previous_track,
                current_track=track,
                next_track=next_track,
                artist_info=artist_info,
                cohost_name=self._cohost_name,
            )
            if not trivia:
                _logger.warning("No monologue generated — prefetch aborted.")
                self._state.transition(DJState.IDLE)
                return

            # ── Synthesise TTS ─────────────────────────────────────────
            # Use DuoTTSProvider during morning show window if configured.
            active_tts = self._active_tts()
            self._state.transition(DJState.SYNTHESIZING)
            with tempfile.NamedTemporaryFile(
                suffix=active_tts.audio_suffix, delete=False, dir=tempfile.gettempdir()
            ) as tmp:
                audio_path = Path(tmp.name)

            success = await active_tts.synthesize(trivia, audio_path)
            if not success:
                _logger.error("TTS synthesis failed — prefetch aborted.")
                self._state.transition(DJState.IDLE)
                return

            # Cache results for the playback-control phase.
            # NOTE: do NOT broadcast monologue here — emit it in _run_interrupt,
            # exactly when the audio starts playing so the frontend is in sync.
            self._prefetched_audio = audio_path
            self._prefetched_monologue = trivia
            _logger.info("Prefetch complete — DJ audio ready for '%s'.", track.name)

        except asyncio.CancelledError:
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            _logger.error("Unexpected error during prefetch: %s", exc, exc_info=True)
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)
        finally:
            # Always return to IDLE after prefetch (playback control will re-drive state).
            if self._state.state in (DJState.ANALYZING, DJState.SYNTHESIZING):
                self._state.transition(DJState.IDLE)

    async def _run_interrupt(self, track: Track) -> None:
        """
        Phase 2 — Talk over the current track outro while ducking Spotify volume.

        Uses pre-generated audio if available; falls back to inline generation
        if prefetch didn't complete in time.
        """
        audio_path: Path | None = None
        try:
            # ── Wait for prefetch to finish if still running ───────────
            if self._prefetch_task and not self._prefetch_task.done():
                _logger.info("Playback control waiting for prefetch to complete…")
                try:
                    await asyncio.wait_for(
                        asyncio.shield(self._prefetch_task),
                        timeout=30.0,
                    )
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    _logger.warning("Prefetch did not complete in time — skipping interrupt.")
                    return

            audio_path = self._prefetched_audio
            if audio_path is None or not audio_path.exists():
                _logger.warning("No pre-generated audio available — skipping interrupt.")
                return

            # Take ownership so _discard_prefetched_audio won't delete it mid-play.
            self._prefetched_audio = None
            monologue = self._prefetched_monologue
            self._prefetched_monologue = ""

            self._state.transition(DJState.DUCKING_IN)

            # ── Play DJ audio over the outro with volume ducking ───────
            await self._play_with_ducking(audio_path, 0.0, display_text=monologue)

            self._last_interrupt_time = time.monotonic()
            self._songs_since_last_dj = 0
            self._next_dj_at = self._roll_next_interval()
            _logger.info("DJ talk-over complete — next in %d songs.", self._next_dj_at)

        except asyncio.CancelledError:
            _logger.info("DJ interrupt task cancelled.")
            raise
        except Exception as exc:
            _logger.error("Unexpected error in DJ interrupt: %s", exc, exc_info=True)
        finally:
            self._state.transition(DJState.IDLE)
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)

    def _discard_prefetched_audio(self) -> None:
        """Delete any cached prefetch audio and reset prefetch state."""
        if self._prefetched_audio and self._prefetched_audio.exists():
            try:
                self._prefetched_audio.unlink()
            except OSError:
                pass
        self._prefetched_audio = None
        self._prefetched_monologue = ""

    async def _play_with_ducking(
        self,
        audio_path: Path,
        estimated_duration: float,
        display_text: str | None = None,
    ) -> None:
        """
        Duck the music, play the TTS clip via pygame, then unduck.

        Plays the audio file in a thread executor (pygame is threadsafe)
        while the asyncio ducker handles the volume ramp concurrently.
        If *display_text* is provided, it is broadcast exactly when pygame
        starts playback and cleared exactly when playback ends.
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
        bed_channel = self._start_bed()
        self._state.transition(DJState.SPEAKING)
        duck_task = asyncio.create_task(self._ducker.duck_for(actual_duration))

        # Offset playback start to allow the duck-in ramp to begin first.
        duck_in_delay = self._ducker._config.duck_in_ms / 1000.0  # noqa: SLF001
        await asyncio.sleep(duck_in_delay)

        def on_play() -> None:
            if display_text is None:
                return
            self._last_monologue = display_text
            self._broadcast_event("monologue", {"text": display_text})

        def on_end() -> None:
            if display_text is None:
                return
            self._last_monologue = ""
            self._broadcast_event("monologue_clear", {})

        try:
            await loop.run_in_executor(
                None, self._play_audio_sync, audio_path, on_play, on_end
            )
            await duck_task
        finally:
            self._stop_bed(bed_channel)

    @staticmethod
    def _play_audio_sync(
        audio_path: Path,
        on_play: Callable[[], None] | None = None,
        on_end: Callable[[], None] | None = None,
    ) -> None:
        """Blocking pygame playback (runs in executor)."""
        played = False
        try:
            pygame.mixer.music.load(str(audio_path))
            pygame.mixer.music.play()
            played = True
            if on_play:
                on_play()
            # Poll until playback finishes.
            import time as _time
            while pygame.mixer.music.get_busy():
                _time.sleep(0.05)
        except Exception as exc:
            _logger.error("pygame playback error: %s", exc)
        finally:
            if played and on_end:
                on_end()

    # ------------------------------------------------------------------ #
    # Radio Imaging helpers                                                #
    # ------------------------------------------------------------------ #

    def _start_bed(self) -> "pygame.mixer.Channel | None":
        """
        Start the background music bed on a dedicated mixer channel.

        Returns the channel so the caller can stop it later, or *None* if
        imaging is disabled, the file is missing, or pygame errors.
        """
        if not self._module_config.radio_imaging_enabled:
            return None
        bed_paths = self._module_config.imaging_bed_paths
        if not bed_paths:
            return None
        raw = Path(random.choice(bed_paths))
        bed_path = raw if raw.is_absolute() else Path(__file__).parent.parent.parent / raw
        if not bed_path.exists():
            _logger.debug("Radio imaging: bed file not found at %s — skipping.", bed_path)
            return None
        try:
            sound = pygame.mixer.Sound(str(bed_path))
            sound.set_volume(self._module_config.imaging_bed_volume)
            channel = pygame.mixer.Channel(1)
            channel.play(sound, loops=-1)
            _logger.debug("Radio imaging: bed started (vol=%.2f).", self._module_config.imaging_bed_volume)
            return channel
        except Exception as exc:
            _logger.warning("Radio imaging: could not start bed: %s", exc)
            return None

    @staticmethod
    def _stop_bed(channel: "pygame.mixer.Channel | None") -> None:
        """Fade out and stop the background bed channel."""
        if channel is None:
            return
        try:
            channel.fadeout(1000)  # 1-second fade
        except Exception as exc:
            _logger.debug("Radio imaging: bed stop error: %s", exc)

    # ------------------------------------------------------------------ #
    # Active TTS selection (solo vs duo)                                   #
    # ------------------------------------------------------------------ #

    def _active_tts(self) -> TTSProvider:
        """
        Return the appropriate TTS provider for the current moment.

        During the duo-mode window (08:00–10:59), if a co-host voice is
        configured and the ``duo_mode_enabled`` flag is set, returns a
        :class:`DuoTTSProvider` wrapping both voices.  Otherwise returns
        the primary TTS provider unchanged.
        """
        if (
            self._tts_cohost is not None
            and self._module_config.duo_mode_enabled
            and is_duo_time()
        ):
            from src.tts.duo_provider import DuoTTSProvider
            return DuoTTSProvider(
                self._tts, self._tts_cohost,
                name_a="RYAN", name_b=self._cohost_name.upper(),
            )
        return self._tts

    # ------------------------------------------------------------------ #
    # Top-of-hour news scheduler                                          #
    # ------------------------------------------------------------------ #

    def _start_news_scheduler(self) -> None:
        """Launch the background news scheduler loop as an asyncio task."""
        if not self._module_config.top_of_hour_news_enabled:
            _logger.debug("Top-of-hour news is disabled in module config.")
            return
        self._news_task = asyncio.create_task(
            self._news_scheduler_loop(), name="news_scheduler"
        )
        _logger.info("Top-of-hour news scheduler started.")

    async def _news_scheduler_loop(self) -> None:
        """Sleep until the next :00, fire a bulletin, repeat while running."""
        while self._running:
            now = datetime.now()
            # Seconds until the next top of the hour.
            seconds_until_next_hour = (
                (60 - now.minute) * 60
                - now.second
                + (1_000_000 - now.microsecond) / 1_000_000
            )
            _logger.debug(
                "News scheduler: next bulletin in %.0fs.", seconds_until_next_hour
            )
            try:
                await asyncio.sleep(seconds_until_next_hour)
            except asyncio.CancelledError:
                return

            if not self._running:
                return
            asyncio.create_task(self._run_news_bulletin(), name="news_bulletin")

    async def _run_news_bulletin(self) -> None:
        """Fetch, format, synthesize, and broadcast a top-of-hour news bulletin."""
        if not self._module_config.top_of_hour_news_enabled:
            return

        if self._state.is_busy:
            _logger.warning(
                "Top-of-hour news skipped — DJ is currently busy (%s).",
                self._state.state.name,
            )
            return

        hour = datetime.now().hour
        _logger.info("Broadcasting top-of-hour news bulletin (%02d:00).", hour)
        audio_path: Path | None = None
        loop = asyncio.get_running_loop()
        try:
            # ── Fetch and format ────────────────────────────────
            news = await loop.run_in_executor(None, self._news_fetcher.fetch)
            self._cache_news_links(news.articles, datetime.now(), hour)
            script = await self._trivia.generate_news_script(news, hour)

            # ── Synthesize to temp WAV ──────────────────────────
            self._state.transition(DJState.SYNTHESIZING)
            with tempfile.NamedTemporaryFile(
                suffix=self._tts.audio_suffix, delete=False, dir=tempfile.gettempdir()
            ) as tmp:
                audio_path = Path(tmp.name)
            success = await self._tts.synthesize(script, audio_path)
            if not success:
                _logger.error("News bulletin: TTS synthesis failed.")
                return

            # ── Pause Spotify, play bulletin and optional commercial, resume ──
            self._state.transition(DJState.DUCKING_IN)
            await loop.run_in_executor(None, self._spotify_client.pause_playback)
            await self._play_with_ducking(audio_path, 0.0, display_text=script)
            await self._run_fake_commercial_if_due(hour)
            await loop.run_in_executor(None, self._spotify_client.resume_playback)

            _logger.info("Top-of-hour news bulletin complete.")

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.error("News bulletin error: %s", exc, exc_info=True)
        finally:
            self._state.transition(DJState.IDLE)
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)

    async def _run_fake_commercial_if_due(self, hour: int) -> None:
        """Generate and play one fake commercial after news, at most once per hour."""
        if not self._module_config.fake_commercials_enabled:
            return
        if self._last_fake_commercial_hour == hour:
            return

        audio_path: Path | None = None
        try:
            script = await self._trivia.generate_fake_commercial(hour)
            if not script:
                _logger.warning("Fake commercial skipped — no script generated.")
                return

            self._state.transition(DJState.SYNTHESIZING)
            with tempfile.NamedTemporaryFile(
                suffix=self._tts.audio_suffix, delete=False, dir=tempfile.gettempdir()
            ) as tmp:
                audio_path = Path(tmp.name)

            success = await self._tts.synthesize(script, audio_path)
            if not success:
                _logger.error("Fake commercial: TTS synthesis failed.")
                return

            await self._play_with_ducking(audio_path, 0.0, display_text=script)
            self._last_fake_commercial_hour = hour
            _logger.info("Fake commercial complete.")

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.error("Fake commercial error: %s", exc, exc_info=True)
        finally:
            if audio_path and audio_path.exists():
                audio_path.unlink(missing_ok=True)
