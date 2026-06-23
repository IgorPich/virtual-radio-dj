"""DJ state machine managed by the Orchestrator."""

from __future__ import annotations

from enum import Enum, auto

from src.utils.logger import get_logger

_logger = get_logger("core.state_manager")


class DJState(Enum):
    """All possible states the DJ can be in."""

    IDLE = auto()        # Waiting; no active DJ action.
    ANALYZING = auto()   # Generating trivia via LLM.
    SYNTHESIZING = auto()  # Converting trivia to voice via TTS.
    DUCKING_IN = auto()  # Fading music volume down.
    SPEAKING = auto()    # Playing DJ voice audio.
    DUCKING_OUT = auto() # Fading music volume back up.


class StateManager:
    """
    Tracks the current :class:`DJState` and logs every transition.

    The manager is intentionally simple: it does not enforce valid
    transition graphs, leaving that responsibility to the ``Orchestrator``.
    """

    def __init__(self) -> None:
        self._state = DJState.IDLE
        self._on_transition: list = []

    @property
    def state(self) -> DJState:
        return self._state

    @property
    def is_busy(self) -> bool:
        """Return *True* if the DJ is doing anything other than idling."""
        return self._state != DJState.IDLE

    def on_transition(self, callback) -> None:
        """Register a callback ``(old_state, new_state) -> None``."""
        self._on_transition.append(callback)

    def transition(self, new_state: DJState) -> None:
        """
        Move to *new_state* and log the change.

        Args:
            new_state: Target state.
        """
        if new_state == self._state:
            return
        old = self._state
        _logger.debug("DJ state: %s → %s", old.name, new_state.name)
        self._state = new_state
        for cb in self._on_transition:
            try:
                cb(old, new_state)
            except Exception:
                pass
