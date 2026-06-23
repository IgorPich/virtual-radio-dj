"""Read-only Spotify data models (dataclasses — no business logic)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Track:
    """A single Spotify track as returned by the playback API."""

    id: str
    name: str
    artist: str
    duration_ms: int
    progress_ms: int
    album_art_url: str = ""

    @property
    def remaining_ms(self) -> int:
        """Milliseconds remaining until track end."""
        return max(0, self.duration_ms - self.progress_ms)

    @property
    def remaining_sec(self) -> float:
        """Seconds remaining until track end."""
        return self.remaining_ms / 1000.0


@dataclass(frozen=True)
class PlaybackState:
    """Snapshot of current Spotify playback."""

    is_playing: bool
    current_track: Track | None
    queue: list[Track] = field(default_factory=list)

    @property
    def has_track(self) -> bool:
        return self.current_track is not None
