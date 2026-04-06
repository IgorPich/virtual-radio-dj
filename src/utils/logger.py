"""Structured logger factory for the application."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path

import yaml

_LOGGING_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "logging.yml"
_ROOT_LOGGER_NAME = "virtual_radio_dj"


def configure_logging(debug: bool = False) -> None:
    """
    Load the YAML logging configuration and optionally force DEBUG level.

    Should be called once at application startup before any logger is used.

    Args:
        debug: When *True*, override all handler levels to DEBUG.
    """
    if _LOGGING_CONFIG_PATH.exists():
        with _LOGGING_CONFIG_PATH.open("r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        if debug:
            for handler in cfg.get("handlers", {}).values():
                handler["level"] = "DEBUG"
            for logger in cfg.get("loggers", {}).values():
                logger["level"] = "DEBUG"
        logging.config.dictConfig(cfg)
    else:
        level = logging.DEBUG if debug else logging.INFO
        logging.basicConfig(
            format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            level=level,
        )


def get_logger(name: str) -> logging.Logger:
    """
    Return a child logger under the application root namespace.

    Args:
        name: Sub-name appended to the root logger namespace, e.g.
              ``"audio.ducker"`` → ``"virtual_radio_dj.audio.ducker"``.

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
