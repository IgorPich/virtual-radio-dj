"""Pydantic v2 configuration schemas for all subsystems."""

from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AudioConfig(BaseModel):
    """Volume-ducking parameters for the Spotify audio session."""

    spotify_process_name: str = "Spotify.exe"
    duck_target_volume: float = Field(0.25, ge=0.0, le=1.0)
    duck_in_ms: int = Field(600, ge=50)
    duck_out_ms: int = Field(900, ge=50)
    tail_silence_ms: int = Field(300, ge=0)


class LLMConfig(BaseModel):
    """Settings for the local Ollama LLM endpoint."""

    endpoint: str = "http://localhost:11434"
    model: str = "mistral"
    temperature: float = Field(0.8, ge=0.0, le=2.0)
    timeout_sec: int = Field(60, ge=5)


class TTSConfig(BaseModel):
    """Text-to-speech provider selection and options."""

    # Registered provider keys: "local_gtts" | "elevenlabs" | "piper"
    provider: str = "local_gtts"
    language: str = "en"
    slow: bool = False

    # ElevenLabs-specific settings (only used when provider="elevenlabs")
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_turbo_v2_5"

    # Piper-specific settings (only used when provider="piper")
    piper_model_path: str = ""
    piper_model_name: str = "en_US-ryan-high"
    piper_exe_path: str = ""
    piper_speaker_id: int | None = None

    # Duo-mode co-host voice (only used when duo_mode_enabled and provider="piper")
    piper_model_path_cohost: str = ""
    cohost_name: str = "Emma"


class SpotifyConfig(BaseModel):
    """Spotify OAuth credentials and polling behaviour."""

    client_id: str
    client_secret: str
    redirect_uri: str = "http://localhost:8888/callback"
    poll_interval_sec: float = Field(1.0, ge=0.1)
    trigger_before_end_sec: float = Field(20.0, ge=5.0)


class DJConfig(BaseModel):
    """DJ behaviour tuning — frequency, skip handling."""

    song_interval_min: int = Field(2, ge=1)
    song_interval_max: int = Field(4, ge=1)
    skip_grace_period_sec: float = Field(60.0, ge=5.0)


class ApiConfig(BaseModel):
    """Flask stub server settings."""

    host: str = "127.0.0.1"
    port: int = Field(5000, ge=1024, le=65535)


class AppSettings(BaseSettings):
    """
    Root settings object loaded from environment variables and/or a .env file.

    Nested models are populated via double-underscore prefixes, e.g.
    ``AUDIO__DUCK_TARGET_VOLUME=0.3`` maps to ``settings.audio.duck_target_volume``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    audio: AudioConfig = Field(default_factory=AudioConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    spotify: SpotifyConfig  # Required — no default; must be set in .env
    dj: DJConfig = Field(default_factory=DJConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    debug: bool = False
