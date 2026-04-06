"""Mock Spotify API response payloads."""

CURRENT_PLAYBACK_PLAYING = {
    "is_playing": True,
    "progress_ms": 340_000,
    "item": {
        "id": "track_1",
        "name": "Bohemian Rhapsody",
        "duration_ms": 355_000,
        "artists": [{"name": "Queen"}],
    },
}

CURRENT_PLAYBACK_PAUSED = {
    "is_playing": False,
    "progress_ms": 100_000,
    "item": {
        "id": "track_2",
        "name": "Stairway to Heaven",
        "duration_ms": 480_000,
        "artists": [{"name": "Led Zeppelin"}],
    },
}

CURRENT_PLAYBACK_NONE: dict = {}
