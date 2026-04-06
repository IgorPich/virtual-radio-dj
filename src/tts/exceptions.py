"""TTS-domain exceptions."""

from __future__ import annotations


class TTSError(Exception):
    """Base class for text-to-speech errors."""


class TTSSynthesisError(TTSError):
    """Raised when audio synthesis fails."""


class TTSProviderNotImplementedError(TTSError):
    """Raised when a stub provider method is called."""
