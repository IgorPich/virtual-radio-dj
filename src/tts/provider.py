"""Abstract TTSProvider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TTSProvider(ABC):
    """
    Plugin interface for text-to-speech back-ends.

    All implementations must fulfil this contract.  The ``Orchestrator``
    depends only on this abstract type, so any concrete provider can be
    injected without modifying orchestration logic.
    """

    @abstractmethod
    async def synthesize(self, text: str, output_path: Path) -> bool:
        """
        Convert *text* to speech and write the audio to *output_path*.

        Args:
            text:        Script to synthesize (plain text).
            output_path: Filesystem path for the output audio file.
                         The parent directory must already exist.
                         The file extension determines the format
                         (e.g. ``.mp3``).

        Returns:
            *True* if synthesis succeeded and the file was written,
            *False* otherwise.
        """

    @abstractmethod
    async def estimate_duration(self, text: str) -> float:
        """
        Estimate the audio duration (in seconds) for *text*.

        The estimate is used to size the ducking hold window before the
        actual audio file has been synthesized.  It does not need to be
        exact; a slight over-estimate is preferable to cutting music
        back in too early.

        Args:
            text: Script text.

        Returns:
            Estimated duration in seconds.
        """
