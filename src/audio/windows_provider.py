"""Windows WASAPI audio provider via pycaw."""

from __future__ import annotations

import ctypes
import sys
from typing import Any

from src.audio.exceptions import VolumeControlError
from src.audio.provider import AudioProvider
from src.utils.logger import get_logger

if sys.platform != "win32":
    raise ImportError("WindowsAudioProvider is only supported on Windows.")

from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume  # noqa: E402

_logger = get_logger("audio.windows_provider")


class WindowsAudioProvider(AudioProvider):
    """
    Controls the per-process audio session volume on Windows using WASAPI
    via the ``pycaw`` library.

    Session objects are cached after the first successful lookup to avoid
    re-enumerating all sessions on every volume call.  The cache is
    invalidated automatically when the cached session becomes stale.

    Args:
        process_name: Executable name to target (e.g. ``"Spotify.exe"``).
    """

    def __init__(self, process_name: str = "Spotify.exe") -> None:
        self._process_name = process_name
        self._cached_volume_ctrl: Any | None = None

    # ------------------------------------------------------------------ #
    # Public API (AudioProvider)                                           #
    # ------------------------------------------------------------------ #

    def get_volume(self) -> float | None:
        """Return current session volume or *None* if process not found."""
        ctrl = self._get_volume_control()
        if ctrl is None:
            return None
        try:
            return float(ctrl.GetMasterVolume())
        except Exception as exc:
            _logger.warning("get_volume failed, invalidating cache: %s", exc)
            self._cached_volume_ctrl = None
            return None

    def set_volume(self, volume: float) -> bool:
        """
        Set the process audio session to *volume* immediately.

        Args:
            volume: Target level in [0.0, 1.0].  Values outside this range
                    are clamped silently.

        Returns:
            *True* on success, *False* if the process session was not found.

        Raises:
            VolumeControlError: If the WASAPI call itself raises.
        """
        volume = max(0.0, min(1.0, volume))
        ctrl = self._get_volume_control()
        if ctrl is None:
            return False
        try:
            ctrl.SetMasterVolume(volume, None)
            return True
        except Exception as exc:
            self._cached_volume_ctrl = None
            raise VolumeControlError(
                f"WASAPI SetMasterVolume failed for '{self._process_name}': {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_volume_control(self) -> Any | None:
        """Return a valid cached ISimpleAudioVolume, or search for a fresh one."""
        if self._cached_volume_ctrl is not None:
            if self._is_ctrl_valid(self._cached_volume_ctrl):
                return self._cached_volume_ctrl
            self._cached_volume_ctrl = None

        ctrl = self._find_session_volume()
        self._cached_volume_ctrl = ctrl
        return ctrl

    def _find_session_volume(self) -> Any | None:
        """Enumerate WASAPI sessions and return the volume control for the target process."""
        try:
            sessions = AudioUtilities.GetAllSessions()
        except Exception as exc:
            _logger.error("Failed to enumerate audio sessions: %s", exc)
            return None

        for session in sessions:
            if session.Process is None:
                continue
            if self._process_name.lower() in session.Process.name().lower():
                _logger.debug("Found audio session for '%s'.", self._process_name)
                return session.SimpleAudioVolume

        _logger.debug("Audio session for '%s' not found.", self._process_name)
        return None

    @staticmethod
    def _is_ctrl_valid(ctrl: Any) -> bool:
        """Return *True* if the cached COM object is still usable."""
        try:
            _ = ctrl.GetMasterVolume()
            return True
        except Exception:
            return False
