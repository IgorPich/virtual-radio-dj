"""Spotipy wrapper — authentication and raw playback state fetching."""

from __future__ import annotations

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from src.config.schemas import SpotifyConfig
from src.spotify.exceptions import SpotifyAuthError, SpotifyAPIError
from src.spotify.models import PlaybackState, Track
from src.utils.logger import get_logger

_logger = get_logger("spotify.client")

_SCOPES = (
    "user-read-playback-state "
    "user-read-currently-playing "
    "user-modify-playback-state"
)


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
        images = item.get("album", {}).get("images") or []
        album_art_url = images[0]["url"] if images else ""
        track = Track(
            id=item.get("id", ""),
            name=item.get("name", "Unknown"),
            artist=item["artists"][0]["name"] if item.get("artists") else "Unknown",
            duration_ms=item.get("duration_ms", 0),
            progress_ms=data.get("progress_ms") or 0,
            album_art_url=album_art_url,
        )

        return PlaybackState(
            is_playing=bool(data.get("is_playing")),
            current_track=track,
        )

    def get_next_in_queue(self) -> Track | None:
        """
        Fetch the next upcoming track from the user's Spotify queue.

        Returns:
            A :class:`Track` representing the next queued song, or *None*
            if the queue is empty or the API call fails.
        """
        if self._sp is None:
            raise RuntimeError("Call SpotifyClient.connect() before get_next_in_queue().")

        try:
            data = self._sp.queue()
        except Exception as exc:
            _logger.warning("Failed to fetch Spotify queue: %s", exc)
            return None

        queue_items = data.get("queue") if data else None
        if not queue_items:
            return None

        item = queue_items[0]
        images = item.get("album", {}).get("images") or []
        album_art_url = images[0]["url"] if images else ""
        return Track(
            id=item.get("id", ""),
            name=item.get("name", "Unknown"),
            artist=item["artists"][0]["name"] if item.get("artists") else "Unknown",
            duration_ms=item.get("duration_ms", 0),
            progress_ms=0,
            album_art_url=album_art_url,
        )

    def get_artist_info(self, artist_name: str) -> dict:
        """
        Search for an artist by name and return enrichment data.

        Returns a dict with keys ``genres`` (list[str]), ``popularity`` (int 0-100),
        and ``followers`` (int).  Returns empty defaults on any failure.
        """
        if self._sp is None:
            raise RuntimeError("Call SpotifyClient.connect() before get_artist_info().")

        empty: dict = {"genres": [], "popularity": 0, "followers": 0}
        try:
            results = self._sp.search(q=f"artist:{artist_name}", type="artist", limit=1)
            items = (results or {}).get("artists", {}).get("items") or []
            if not items:
                return empty
            a = items[0]
            return {
                "genres": a.get("genres") or [],
                "popularity": int(a.get("popularity") or 0),
                "followers": int((a.get("followers") or {}).get("total") or 0),
            }
        except Exception as exc:
            _logger.warning("get_artist_info failed for '%s': %s", artist_name, exc)
            return empty

    def pause_playback(self) -> bool:
        """Pause Spotify playback. Returns True on success."""
        if self._sp is None:
            return False
        try:
            self._sp.pause_playback()
            return True
        except Exception as exc:
            _logger.warning("pause_playback failed: %s", exc)
            return False

    def skip_to_next(self) -> bool:
        """Skip to the next track. Returns True on success."""
        if self._sp is None:
            return False
        try:
            self._sp.next_track()
            return True
        except Exception as exc:
            _logger.warning("skip_to_next failed: %s", exc)
            return False

    def resume_playback(self) -> bool:
        """Resume Spotify playback. Returns True on success."""
        if self._sp is None:
            return False
        try:
            self._sp.start_playback()
            return True
        except Exception as exc:
            _logger.warning("resume_playback failed: %s", exc)
            return False
