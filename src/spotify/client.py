"""Spotipy wrapper — authentication and raw playback state fetching."""

from __future__ import annotations

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from src.config.schemas import SpotifyConfig
from src.spotify.exceptions import SpotifyAuthError, SpotifyAPIError
from src.spotify.models import PlaybackState, Track
from src.utils.logger import get_logger

_logger = get_logger("spotify.client")

_SCOPES = "user-read-playback-state user-read-currently-playing"


class SpotifyClient:
    """
    Authenticated Spotipy wrapper that reads current playback state.

    Authentication uses the OAuth PKCE + cache-file flow provided by
    Spotipy.  On first run the user is redirected to their browser to
    authorise the app; subsequent runs use the cached token file.

    Args:
        config: Spotify configuration (credentials, redirect URI).
    """

    def __init__(self, config: SpotifyConfig) -> None:
        self._config = config
        self._sp: spotipy.Spotify | None = None

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        """
        Initialise the Spotipy client and verify authentication.

        Should be called once at startup before ``get_playback_state``.

        Raises:
            SpotifyAuthError: If OAuth credentials are invalid or the
                              user denies authorisation.
        """
        try:
            auth_manager = SpotifyOAuth(
                client_id=self._config.client_id,
                client_secret=self._config.client_secret,
                redirect_uri=self._config.redirect_uri,
                scope=_SCOPES,
                open_browser=True,
            )
            self._sp = spotipy.Spotify(auth_manager=auth_manager)
            # Trigger a test call to validate credentials eagerly.
            self._sp.current_user()
            _logger.info("Spotify authentication successful.")
        except Exception as exc:
            raise SpotifyAuthError(f"Spotify OAuth failed: {exc}") from exc

    def get_playback_state(self) -> PlaybackState:
        """
        Fetch the current Spotify playback state.

        Returns:
            A populated :class:`PlaybackState` instance.  If nothing is
            playing, ``is_playing`` will be *False* and ``current_track``
            will be *None*.

        Raises:
            SpotifyAPIError: On unexpected API failures.
            RuntimeError:    If ``connect()`` was not called first.
        """
        if self._sp is None:
            raise RuntimeError("Call SpotifyClient.connect() before get_playback_state().")

        try:
            data = self._sp.current_playback()
        except Exception as exc:
            raise SpotifyAPIError(f"Spotify API error: {exc}") from exc

        if not data or not data.get("item"):
            return PlaybackState(is_playing=False, current_track=None)

        item = data["item"]
        track = Track(
            id=item.get("id", ""),
            name=item.get("name", "Unknown"),
            artist=item["artists"][0]["name"] if item.get("artists") else "Unknown",
            duration_ms=item.get("duration_ms", 0),
            progress_ms=data.get("progress_ms") or 0,
        )

        return PlaybackState(
            is_playing=bool(data.get("is_playing")),
            current_track=track,
        )
