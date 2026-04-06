"""Spotify-domain exceptions."""

from __future__ import annotations


class SpotifyError(Exception):
    """Base class for Spotify integration errors."""


class SpotifyAuthError(SpotifyError):
    """Raised when OAuth authentication fails."""


class SpotifyAPIError(SpotifyError):
    """Raised on unexpected API responses."""
