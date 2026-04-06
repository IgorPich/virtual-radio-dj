"""Config loader — constructs AppSettings from .env / environment."""

from __future__ import annotations

from pathlib import Path

from src.config.schemas import AppSettings


def load_settings(env_file: str | Path | None = None) -> AppSettings:
    """
    Build and return validated ``AppSettings``.

    Args:
        env_file: Optional path to a ``.env`` file.  Defaults to the
                  ``.env`` file in the current working directory when
                  *None* (Pydantic behaviour).

    Returns:
        Fully validated ``AppSettings`` instance.

    Raises:
        pydantic_settings.PydanticSettingsError: If required fields
            (e.g. Spotify credentials) are missing.
    """
    if env_file is not None:
        return AppSettings(_env_file=str(env_file))  # type: ignore[call-arg]
    return AppSettings()
