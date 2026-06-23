"""Unit tests for ModuleConfig loading and defaults."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.modules import ModuleConfig, load_module_config


class TestModuleConfigDefaults:
    def test_returns_defaults_when_file_absent(self, tmp_path: Path) -> None:
        config = load_module_config(tmp_path / "nonexistent.json")
        assert isinstance(config, ModuleConfig)
        assert config.top_of_hour_news_enabled is True
        assert config.duo_mode_enabled is False
        assert config.radio_imaging_enabled is True
        assert config.fake_commercials_enabled is False

    def test_returns_defaults_for_malformed_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "modules.json"
        bad_file.write_text("{not valid json", encoding="utf-8")
        with pytest.warns(UserWarning):
            config = load_module_config(bad_file)
        assert isinstance(config, ModuleConfig)

    def test_default_bed_volume_within_range(self) -> None:
        config = ModuleConfig()
        assert 0.0 <= config.imaging_bed_volume <= 1.0


class TestModuleConfigParsing:
    def test_parses_all_fields_from_valid_json(self, tmp_path: Path) -> None:
        data = {
            "top_of_hour_news_enabled": False,
            "duo_mode_enabled": False,
            "radio_imaging_enabled": False,
            "imaging_bed_paths": ["custom/bed.mp3", "custom/bed2.mp3"],
            "imaging_bed_volume": 0.25,
            "fake_commercials_enabled": True,
        }
        config_file = tmp_path / "modules.json"
        config_file.write_text(json.dumps(data), encoding="utf-8")

        config = load_module_config(config_file)

        assert config.top_of_hour_news_enabled is False
        assert config.duo_mode_enabled is False
        assert config.radio_imaging_enabled is False
        assert config.imaging_bed_paths == ["custom/bed.mp3", "custom/bed2.mp3"]
        assert config.imaging_bed_volume == pytest.approx(0.25)
        assert config.fake_commercials_enabled is True

    def test_partial_json_uses_defaults_for_missing_fields(self, tmp_path: Path) -> None:
        data = {"top_of_hour_news_enabled": False}
        config_file = tmp_path / "modules.json"
        config_file.write_text(json.dumps(data), encoding="utf-8")

        config = load_module_config(config_file)

        assert config.top_of_hour_news_enabled is False
        assert config.duo_mode_enabled is False  # lightweight default

    def test_legacy_removed_fields_are_ignored(self, tmp_path: Path) -> None:
        data = {
            "office_ads_enabled": True,
            "quizzes_enabled": True,
            "shoutouts_enabled": True,
        }
        config_file = tmp_path / "modules.json"
        config_file.write_text(json.dumps(data), encoding="utf-8")

        config = load_module_config(config_file)

        assert config.fake_commercials_enabled is False
        assert not hasattr(config, "office_ads_enabled")
        assert not hasattr(config, "quizzes_enabled")
        assert not hasattr(config, "shoutouts_enabled")
