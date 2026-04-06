"""Core orchestration exceptions."""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base class for orchestration errors."""


class AlreadyRunningError(OrchestratorError):
    """Raised when start() is called on an already-running orchestrator."""
