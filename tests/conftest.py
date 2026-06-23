"""Shared pytest fixtures used across all test modules."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from src.audio.ducker import AudioDucker, DuckingConfig
from src.audio.provider import AudioProvider
from src.config.schemas import (
    ApiConfig,
    AppSettings,
    AudioConfig,
    LLMConfig,
    SpotifyConfig,
    TTSConfig,
)
from src.core.state_manager import DJState, StateManager
from src.llm.client import OllamaClient
from src.llm.trivia_generator import TriviaGenerator
from src.spotify.client import SpotifyClient
from src.spotify.models import PlaybackState, Track
from src.spotify.poller import SpotifyPoller
from src.config.modules import ModuleConfig
from src.tts.provider import TTSProvider


# ──────────────────────────────────────────────────────────────────────
# Configuration fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def audio_config() -> AudioConfig:
    return AudioConfig()


@pytest.fixture()
def llm_config() -> LLMConfig:
    return LLMConfig()


@pytest.fixture()
def tts_config() -> TTSConfig:
    return TTSConfig()


@pytest.fixture()
def spotify_config() -> SpotifyConfig:
    return SpotifyConfig(
        client_id="test_client_id",
        client_secret="test_client_secret",
    )


@pytest.fixture()
def app_settings(spotify_config: SpotifyConfig) -> AppSettings:
    return AppSettings(spotify=spotify_config)


@pytest.fixture()
def ducking_config() -> DuckingConfig:
    return DuckingConfig(
        duck_target_volume=0.25,
        duck_in_ms=100,  # Fast for tests
        duck_out_ms=100,
        tail_silence_ms=0,
    )


# ──────────────────────────────────────────────────────────────────────
# Mock providers
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_audio_provider() -> MagicMock:
    """Mock AudioProvider with sensible defaults."""
    provider = MagicMock(spec=AudioProvider)
    provider.get_volume.return_value = 0.8
    provider.set_volume.return_value = True
    return provider


@pytest.fixture()
def mock_tts_provider() -> AsyncMock:
    """Mock TTSProvider that always succeeds."""
    tts = AsyncMock(spec=TTSProvider)
    tts.synthesize.return_value = True
    tts.estimate_duration.return_value = 3.0
    tts.audio_suffix = ".mp3"
    return tts


@pytest.fixture()
def mock_ollama_client() -> AsyncMock:
    """Mock OllamaClient that returns canned trivia."""
    client = AsyncMock(spec=OllamaClient)
    client.generate.return_value = (
        "Did you know that Freddie Mercury could sing across four octaves?"
    )
    client.is_available.return_value = True
    return client


@pytest.fixture()
def mock_trivia_generator(mock_ollama_client: AsyncMock) -> TriviaGenerator:
    """TriviaGenerator wired to the mock OllamaClient."""
    return TriviaGenerator(client=mock_ollama_client)


@pytest.fixture()
def mock_spotify_client() -> MagicMock:
    """Mock SpotifyClient."""
    client = MagicMock(spec=SpotifyClient)
    client.get_playback_state.return_value = PlaybackState(
        is_playing=True,
        current_track=Track(
            id="track_1",
            name="Bohemian Rhapsody",
            artist="Queen",
            duration_ms=355_000,
            progress_ms=340_000,
        ),
    )
    client.get_next_in_queue.return_value = Track(
        id="track_2",
        name="Under Pressure",
        artist="Queen",
        duration_ms=248_000,
        progress_ms=0,
    )
    client.get_artist_info.return_value = {
        "genres": ["rock", "classic rock"],
        "popularity": 82,
        "followers": 25_000_000,
    }
    client.pause_playback.return_value = True
    client.skip_to_next.return_value = True
    client.resume_playback.return_value = True
    return client


@pytest.fixture()
def mock_spotify_poller(mock_spotify_client: MagicMock) -> MagicMock:
    """Mock SpotifyPoller."""
    poller = MagicMock(spec=SpotifyPoller)
    poller.run = AsyncMock()
    poller.stop = MagicMock()
    return poller


# ──────────────────────────────────────────────────────────────────────
# Composite fixtures
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def audio_ducker(mock_audio_provider: MagicMock, ducking_config: DuckingConfig) -> AudioDucker:
    """AudioDucker wired to the mock provider."""
    return AudioDucker(provider=mock_audio_provider, config=ducking_config)


# ──────────────────────────────────────────────────────────────────────
# Sample data
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture()
def sample_track() -> Track:
    return Track(
        id="track_1",
        name="Bohemian Rhapsody",
        artist="Queen",
        duration_ms=355_000,
        progress_ms=340_000,
    )


@pytest.fixture()
def sample_playback_state(sample_track: Track) -> PlaybackState:
    return PlaybackState(is_playing=True, current_track=sample_track)


@pytest.fixture()
def module_config() -> ModuleConfig:
    """Module config with all optional features disabled for test isolation."""
    return ModuleConfig(
        top_of_hour_news_enabled=False,
        duo_mode_enabled=False,
        radio_imaging_enabled=False,
    )
