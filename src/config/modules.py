"""Module-level feature toggles and runtime configuration."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

_DEFAULT_PATH = Path(__file__).parent.parent.parent / "config" / "modules.json"


class ModuleConfig(BaseModel):
    """Feature flags and settings for optional radio segments."""

    # ── Segment toggles ───────────────────────────────────────────────
    dj_enabled: bool = True
    top_of_hour_news_enabled: bool = True
    duo_mode_enabled: bool = False
    radio_imaging_enabled: bool = True

    # ── Radio imaging ─────────────────────────────────────────────────
    imaging_bed_paths: list[str] = ["assets/bed.mp3"]
    imaging_bed_volume: float = Field(0.12, ge=0.0, le=1.0)

    # ── Optional segments ─────────────────────────────────────────────
    fake_commercials_enabled: bool = False


def load_module_config(path: Path | None = None) -> ModuleConfig:
    """
    Load :class:`ModuleConfig` from *path* (defaults to ``config/modules.json``).

    Returns a default :class:`ModuleConfig` if the file does not exist or
    cannot be parsed, so the application starts gracefully without the file.
    """
    resolved = path or _DEFAULT_PATH
    try:
        with resolved.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return ModuleConfig(**data)
    except FileNotFoundError:
        return ModuleConfig()
    except Exception as exc:  # noqa: BLE001
        import warnings
        warnings.warn(
            f"Could not load modules.json ({exc}); using defaults.",
            stacklevel=2,
        )
        return ModuleConfig()
