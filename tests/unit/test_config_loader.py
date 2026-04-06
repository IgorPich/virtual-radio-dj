"""Unit tests for config loader and logger setup."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest
import yaml

from src.config.loader import load_settings
from src.config.schemas import AppSettings
from src.utils.logger import (
    _LOGGING_CONFIG_PATH,
    _ROOT_LOGGER_NAME,
    configure_logging,
    get_logger,
)


class TestLoadSettings:
    @patch.dict(
        "os.environ",
        {
            "SPOTIFY__CLIENT_ID": "cid",
            "SPOTIFY__CLIENT_SECRET": "csec",
        },
        clear=False,
    )
    def test_load_settings_from_env(self) -> None:
        settings = load_settings()
        assert isinstance(settings, AppSettings)
        assert settings.spotify.client_id == "cid"
        assert settings.spotify.client_secret == "csec"

    def test_load_settings_with_env_file(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "SPOTIFY__CLIENT_ID=file_cid\n"
            "SPOTIFY__CLIENT_SECRET=file_csec\n"
        )
        settings = load_settings(env_file=env_file)
        assert settings.spotify.client_id == "file_cid"

    def test_load_settings_with_string_path(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text(
            "SPOTIFY__CLIENT_ID=str_cid\n"
            "SPOTIFY__CLIENT_SECRET=str_csec\n"
        )
        settings = load_settings(env_file=str(env_file))
        assert settings.spotify.client_id == "str_cid"


class TestConfigureLogging:
    def test_configure_logging_with_yaml_file(self, tmp_path: Path) -> None:
        cfg = {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "virtual_radio_dj": {
                    "level": "INFO",
                    "handlers": ["console"],
                },
            },
        }
        yaml_path = tmp_path / "logging.yml"
        yaml_path.write_text(yaml.dump(cfg))

        with patch("src.utils.logger._LOGGING_CONFIG_PATH", yaml_path):
            configure_logging(debug=False)

        logger = logging.getLogger("virtual_radio_dj")
        assert logger.level == logging.INFO

    def test_configure_logging_debug_override(self, tmp_path: Path) -> None:
        cfg = {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                    "stream": "ext://sys.stdout",
                },
            },
            "loggers": {
                "virtual_radio_dj": {
                    "level": "INFO",
                    "handlers": ["console"],
                },
            },
        }
        yaml_path = tmp_path / "logging.yml"
        yaml_path.write_text(yaml.dump(cfg))

        with patch("src.utils.logger._LOGGING_CONFIG_PATH", yaml_path):
            configure_logging(debug=True)

        logger = logging.getLogger("virtual_radio_dj")
        assert logger.level == logging.DEBUG

    def test_configure_logging_fallback_when_no_yaml(self) -> None:
        missing = Path("/nonexistent/logging.yml")
        with (
            patch("src.utils.logger._LOGGING_CONFIG_PATH", missing),
            patch("logging.basicConfig") as mock_basic,
        ):
            configure_logging(debug=False)
        mock_basic.assert_called_once()
        assert mock_basic.call_args[1]["level"] == logging.INFO

    def test_configure_logging_fallback_debug(self) -> None:
        missing = Path("/nonexistent/logging.yml")
        with (
            patch("src.utils.logger._LOGGING_CONFIG_PATH", missing),
            patch("logging.basicConfig") as mock_basic,
        ):
            configure_logging(debug=True)
        mock_basic.assert_called_once()
        assert mock_basic.call_args[1]["level"] == logging.DEBUG


class TestGetLogger:
    def test_returns_namespaced_logger(self) -> None:
        logger = get_logger("foo.bar")
        assert logger.name == f"{_ROOT_LOGGER_NAME}.foo.bar"
