"""Abstract AudioProvider interface — platform-agnostic contract."""

from __future__ import annotations

from abc import ABC, abstractmethod


class AudioProvider(ABC):
    """
    Defines the interface all platform-specific audio providers must fulfil.

    Implementations control the per-process volume of a named OS audio session
    (e.g. ``Spotify.exe`` on Windows).
    """

    @abstractmethod
    def get_volume(self) -> float | None:
        """
        Return the current volume of the target process (0.0 – 1.0).

        Returns:
            Float volume level, or *None* if the process is not found.
        """

    @abstractmethod
    def set_volume(self, volume: float) -> bool:
        """
        Immediately set the target process volume.

        Args:
            volume: Desired level clamped to [0.0, 1.0].

        Returns:
            *True* on success, *False* if the process is not running.
        """
