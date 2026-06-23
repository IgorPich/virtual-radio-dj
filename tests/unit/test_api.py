"""Unit tests for the Flask API routes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from flask import Flask
from flask.testing import FlaskClient

from src.api.app import create_app
from src.core.orchestrator import RadioDJOrchestrator
from src.core.state_manager import DJState
from src.spotify.models import Track


@pytest.fixture()
def mock_orchestrator() -> MagicMock:
    orch = MagicMock(spec=RadioDJOrchestrator)
    type(orch).dj_state = PropertyMock(return_value=DJState.IDLE)
    type(orch).current_track = PropertyMock(return_value=None)
    type(orch).next_track = PropertyMock(return_value=None)
    type(orch).last_monologue = PropertyMock(return_value="")
    type(orch).runtime_settings = PropertyMock(
        return_value={
            "dj_enabled": True,
            "top_of_hour_news_enabled": True,
            "duo_mode_enabled": False,
            "radio_imaging_enabled": True,
            "fake_commercials_enabled": False,
            "trigger_before_end_sec": 20.0,
        }
    )
    orch.latest_news_links.return_value = {
        "updated_at": "2026-05-05T20:00:00",
        "hour": "20:00",
        "articles": [
            {
                "title": "World headline",
                "url": "https://example.com/world",
                "source": "Example News",
                "category": "world",
            }
        ],
    }
    orch.update_runtime_settings.side_effect = lambda updates: {
        **orch.runtime_settings,
        **updates,
    }
    return orch


@pytest.fixture()
def client(mock_orchestrator: MagicMock) -> FlaskClient:
    app = create_app(mock_orchestrator)
    app.testing = True
    return app.test_client()


class TestHealthEndpoint:
    def test_health_ok(self, client: FlaskClient) -> None:
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"


class TestStatusEndpoint:
    def test_status_idle_no_track(self, client: FlaskClient) -> None:
        resp = client.get("/api/status")
        data = resp.get_json()
        assert data["dj_state"] == "IDLE"
        assert data["current_track"] is None

    def test_status_with_track(
        self, mock_orchestrator: MagicMock, client: FlaskClient
    ) -> None:
        track = Track("t1", "Bohemian Rhapsody", "Queen", 355_000, 340_000)
        type(mock_orchestrator).current_track = PropertyMock(return_value=track)
        type(mock_orchestrator).dj_state = PropertyMock(return_value=DJState.SPEAKING)

        resp = client.get("/api/status")
        data = resp.get_json()
        assert data["dj_state"] == "SPEAKING"
        assert data["current_track"]["artist"] == "Queen"
        assert data["current_track"]["remaining_sec"] == 15.0


class TestSettingsEndpoints:
    def test_get_settings(self, client: FlaskClient) -> None:
        resp = client.get("/api/settings")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["dj_enabled"] is True
        assert data["duo_mode_enabled"] is False
        assert data["fake_commercials_enabled"] is False
        assert "quizzes_enabled" not in data
        assert "shoutouts_enabled" not in data
        assert data["trigger_before_end_sec"] == 20.0

    def test_patch_settings(self, mock_orchestrator: MagicMock, client: FlaskClient) -> None:
        resp = client.patch("/api/settings", json={"dj_enabled": False})
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["dj_enabled"] is False
        mock_orchestrator.update_runtime_settings.assert_called_with({"dj_enabled": False})

    def test_pause_disables_dj(self, client: FlaskClient) -> None:
        resp = client.post("/api/pause")
        assert resp.status_code == 200
        assert resp.get_json()["dj_enabled"] is False

    def test_resume_enables_dj(self, client: FlaskClient) -> None:
        resp = client.post("/api/resume")
        assert resp.status_code == 200
        assert resp.get_json()["dj_enabled"] is True


class TestNewsEndpoint:
    def test_latest_news_links(self, client: FlaskClient) -> None:
        resp = client.get("/api/news/latest")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["hour"] == "20:00"
        assert data["articles"][0]["title"] == "World headline"
        assert data["articles"][0]["category"] == "world"


class TestSettingsUi:
    def test_control_room_has_fake_commercials_without_removed_features(self) -> None:
        root = Path(__file__).resolve().parents[2]
        html = (root / "src" / "api" / "templates" / "index.html").read_text(
            encoding="utf-8"
        )
        js = (root / "src" / "api" / "static" / "app.js").read_text(
            encoding="utf-8"
        )

        assert "Fake Commercials" in html
        assert "control-room" in html
        assert "settings-btn" not in html
        assert "toggle-commercials" in html
        assert "fake_commercials_enabled" in js
        assert "toggle-quizzes" not in html
        assert "toggle-shoutouts" not in html
        assert "quizzes_enabled" not in js
        assert "shoutouts_enabled" not in js
