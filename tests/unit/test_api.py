"""Unit tests for the Flask API routes."""

from __future__ import annotations

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


class TestStubEndpoints:
    def test_pause_returns_501(self, client: FlaskClient) -> None:
        resp = client.post("/api/pause")
        assert resp.status_code == 501

    def test_resume_returns_501(self, client: FlaskClient) -> None:
        resp = client.post("/api/resume")
        assert resp.status_code == 501
