"""Audio-domain exceptions."""

from __future__ import annotations


class AudioError(Exception):
    """Base class for all audio-related errors."""


class ProcessNotFoundError(AudioError):
    """Raised when the target audio process cannot be located."""

    def __init__(self, process_name: str) -> None:
        super().__init__(f"Audio process not found: '{process_name}'")
        self.process_name = process_name


class VolumeControlError(AudioError):
    """Raised when a WASAPI volume operation fails."""
