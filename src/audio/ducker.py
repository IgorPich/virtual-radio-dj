"""AudioDucker — smooth linear-interpolation volume transitions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src.audio.provider import AudioProvider
from src.utils.logger import get_logger

_logger = get_logger("audio.ducker")

# Steps per second during a ramp; higher = smoother but more CPU.
_RAMP_STEPS_PER_SECOND = 25


@dataclass(frozen=True)
class DuckingConfig:
    """Immutable configuration for an ``AudioDucker`` instance."""

    duck_target_volume: float = 0.25
    duck_in_ms: int = 600
    duck_out_ms: int = 900
    tail_silence_ms: int = 300


class AudioDucker:
    """
    Orchestrates a duck-in → hold → duck-out volume cycle around DJ audio.

    The ducker works through the injected :class:`AudioProvider`, making it
    fully testable without a real audio session.

    Args:
        provider:  Platform audio provider.
        config:    Ducking timing and level parameters.
    """

    def __init__(self, provider: AudioProvider, config: DuckingConfig) -> None:
        self._provider = provider
        self._config = config
        self._is_ducking = False

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @property
    def is_ducking(self) -> bool:
        """*True* while a duck-in → hold → duck-out cycle is active."""
        return self._is_ducking

    async def duck_for(self, voice_duration_sec: float) -> bool:
        """
        Execute a full ducking cycle around the DJ voice segment.

        Sequence:
        1. Ramp Spotify volume down to ``duck_target_volume`` over ``duck_in_ms``.
        2. Hold at low volume for *voice_duration_sec* seconds.
        3. Wait an additional ``tail_silence_ms`` of silence.
        4. Ramp Spotify volume back to its pre-duck level over ``duck_out_ms``.

        Args:
            voice_duration_sec: How long the TTS audio will play (seconds).

        Returns:
            *True* on success; *False* if Spotify is not running or audio
            control fails at any point.
        """
        original = self._provider.get_volume()
        if original is None:
            _logger.warning("Duck skipped — Spotify audio session not found.")
            return False

        self._is_ducking = True
        _logger.info(
            "Ducking in from %.2f → %.2f over %dms.",
            original,
            self._config.duck_target_volume,
            self._config.duck_in_ms,
        )

        try:
            await self._ramp(original, self._config.duck_target_volume, self._config.duck_in_ms)
            await asyncio.sleep(voice_duration_sec)
            await asyncio.sleep(self._config.tail_silence_ms / 1000.0)
            _logger.info(
                "Ducking out from %.2f → %.2f over %dms.",
                self._config.duck_target_volume,
                original,
                self._config.duck_out_ms,
            )
            await self._ramp(self._config.duck_target_volume, original, self._config.duck_out_ms)
        except asyncio.CancelledError:
            # Ensure music is always restored even if the task is cancelled.
            _logger.warning("Ducking cancelled — restoring volume to %.2f.", original)
            self._provider.set_volume(original)
            raise
        except Exception as exc:
            _logger.error("Ducking error — attempting volume restore: %s", exc)
            self._provider.set_volume(original)
            return False
        finally:
            self._is_ducking = False

        return True

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    async def _ramp(self, from_vol: float, to_vol: float, duration_ms: int) -> None:
        """
        Linearly ramp volume from *from_vol* to *to_vol* over *duration_ms*.

        Args:
            from_vol:    Starting volume (0.0 – 1.0).
            to_vol:      Target volume (0.0 – 1.0).
            duration_ms: Total ramp duration in milliseconds.
        """
        if duration_ms <= 0 or from_vol == to_vol:
            self._provider.set_volume(to_vol)
            return

        steps = max(1, int(_RAMP_STEPS_PER_SECOND * duration_ms / 1000.0))
        step_sleep = duration_ms / steps / 1000.0

        for i in range(1, steps + 1):
            progress = i / steps
            level = from_vol + (to_vol - from_vol) * progress
            success = self._provider.set_volume(level)
            if not success:
                _logger.warning("set_volume returned False during ramp at step %d/%d.", i, steps)
                break
            if i < steps:
                await asyncio.sleep(step_sleep)
