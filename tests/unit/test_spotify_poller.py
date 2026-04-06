"""Unit tests for Spotify models and poller."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.spotify.models import PlaybackState, Track
from src.spotify.poller import SpotifyPoller


class TestTrack:
    def test_remaining_ms(self, sample_track: Track) -> None:
        assert sample_track.remaining_ms == 15_000

    def test_remaining_sec(self, sample_track: Track) -> None:
        assert sample_track.remaining_sec == 15.0

    def test_frozen(self, sample_track: Track) -> None:
        with pytest.raises(AttributeError):
            sample_track.name = "Another"  # type: ignore[misc]


class TestPlaybackState:
    def test_has_track_true(self, sample_playback_state: PlaybackState) -> None:
        assert sample_playback_state.has_track

    def test_has_track_false(self) -> None:
        state = PlaybackState(is_playing=False, current_track=None)
        assert not state.has_track


class TestSpotifyPoller:
    @pytest.mark.asyncio
    async def test_poller_calls_callback_on_first_state(
        self, mock_spotify_client: MagicMock
    ) -> None:
        poller = SpotifyPoller(client=mock_spotify_client, poll_interval_sec=0.01)
        callback = AsyncMock()

        async def stop_after_call(state, prev):
            await callback(state, prev)
            poller.stop()

        await poller.run(on_state_change=stop_after_call)
        callback.assert_awaited_once()

        # First observation: previous should be None.
        call_args = callback.call_args[0]
        assert call_args[1] is None  # previous state
        assert call_args[0].is_playing is True

    @pytest.mark.asyncio
    async def test_poller_detects_track_change(
        self, mock_spotify_client: MagicMock
    ) -> None:
        poller = SpotifyPoller(client=mock_spotify_client, poll_interval_sec=0.01)
        calls: list = []

        track_a = Track("a", "Song A", "Artist A", 300_000, 290_000)
        track_b = Track("b", "Song B", "Artist B", 200_000, 10_000)

        mock_spotify_client.get_playback_state.side_effect = [
            PlaybackState(is_playing=True, current_track=track_a),
            PlaybackState(is_playing=True, current_track=track_b),
        ]

        async def collect(state, prev):
            calls.append((state, prev))
            if len(calls) >= 2:
                poller.stop()

        await poller.run(on_state_change=collect)
        assert len(calls) == 2
        assert calls[1][0].current_track.id == "b"

    @pytest.mark.asyncio
    async def test_poller_ignores_same_track(
        self, mock_spotify_client: MagicMock
    ) -> None:
        """Same track with only progress change should NOT trigger callback again."""
        poller = SpotifyPoller(client=mock_spotify_client, poll_interval_sec=0.01)
        calls: list = []
        iteration = 0

        track = Track("x", "Same", "Same Artist", 300_000, 100_000)
        mock_spotify_client.get_playback_state.return_value = PlaybackState(
            is_playing=True, current_track=track
        )

        async def collect(state, prev):
            nonlocal iteration
            calls.append(state)
            iteration += 1
            if iteration >= 1:
                poller.stop()

        await poller.run(on_state_change=collect)
        # Should be called exactly once (first observation).
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_poller_detects_play_pause(
        self, mock_spotify_client: MagicMock
    ) -> None:
        poller = SpotifyPoller(client=mock_spotify_client, poll_interval_sec=0.01)
        calls: list = []

        track = Track("t", "T", "A", 300_000, 100_000)
        mock_spotify_client.get_playback_state.side_effect = [
            PlaybackState(is_playing=True, current_track=track),
            PlaybackState(is_playing=False, current_track=track),
        ]

        async def collect(state, prev):
            calls.append(state)
            if len(calls) >= 2:
                poller.stop()

        await poller.run(on_state_change=collect)
        assert len(calls) == 2
        assert calls[0].is_playing is True
        assert calls[1].is_playing is False
