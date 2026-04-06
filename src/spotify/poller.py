"""Continuous asyncio-based Spotify playback poller."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from src.spotify.client import SpotifyClient
from src.spotify.models import PlaybackState
from src.utils.logger import get_logger

_logger = get_logger("spotify.poller")

# Type alias for the state-change callback signature.
StateChangeCallback = Callable[[PlaybackState, PlaybackState | None], Awaitable[None]]


class SpotifyPoller:
    """
    Polls Spotify every *poll_interval_sec* seconds and emits a callback
    whenever the playback state changes (different track, play/pause toggle,
    significant progress delta).

    The poller runs inside an :mod:`asyncio` task; Spotipy's blocking HTTP
    call is offloaded to a thread-pool executor so the event loop is never
    blocked.

    Args:
        client:           Authenticated :class:`SpotifyClient`.
        poll_interval_sec: How often to query the Spotify API (seconds).
    """

    def __init__(self, client: SpotifyClient, poll_interval_sec: float = 1.0) -> None:
        self._client = client
        self._poll_interval = poll_interval_sec
        self._running = False
        self._last_state: PlaybackState | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def run(self, on_state_change: StateChangeCallback) -> None:
        """
        Start the polling loop.  Runs until :meth:`stop` is called.

        Args:
            on_state_change: Async callback invoked with
                             ``(new_state, previous_state)`` on every
                             meaningful state change.
        """
        self._running = True
        _logger.info("Spotify poller started (interval=%.1fs).", self._poll_interval)

        while self._running:
            try:
                state = await self._fetch_state()
                if self._is_changed(state):
                    previous = self._last_state
                    self._last_state = state
                    await on_state_change(state, previous)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                _logger.warning("Spotify poll error (will retry): %s", exc)

            await asyncio.sleep(self._poll_interval)

        _logger.info("Spotify poller stopped.")

    def stop(self) -> None:
        """Signal the polling loop to exit on its next iteration."""
        self._running = False

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _fetch_state(self) -> PlaybackState:
        """Run the blocking Spotipy call in a thread executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._client.get_playback_state)

    def _is_changed(self, state: PlaybackState) -> bool:
        """
        Return *True* if *state* represents a meaningful change from the
        previously seen state.

        Suppresses trivial progress updates (same track, small time delta)
        to prevent hammering the callback on every poll tick.
        """
        if self._last_state is None:
            return True  # First observation always counts.

        last = self._last_state
        new = state

        # Play/pause or track swap always counts.
        if new.is_playing != last.is_playing:
            return True
        if new.has_track != last.has_track:
            return True
        if new.current_track and last.current_track:
            if new.current_track.id != last.current_track.id:
                return True
        return False
