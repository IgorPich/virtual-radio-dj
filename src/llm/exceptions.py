"""LLM-domain exceptions."""

from __future__ import annotations


class LLMError(Exception):
    """Base class for LLM-related errors."""


class LLMConnectionError(LLMError):
    """Raised when the Ollama server cannot be reached."""


class LLMTimeoutError(LLMError):
    """Raised when inference exceeds the configured timeout."""


class LLMResponseError(LLMError):
    """Raised for unexpected or malformed Ollama API responses."""
