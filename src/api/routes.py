"""REST API route definitions."""

from __future__ import annotations

from flask import Flask, current_app, jsonify
from flask.wrappers import Response

from src.core.orchestrator import RadioDJOrchestrator


def _orchestrator() -> RadioDJOrchestrator:
    return current_app.extensions["orchestrator"]


def register_routes(app: Flask) -> None:
    """Attach all API routes to *app*."""

    @app.get("/api/health")
    def health() -> Response:
        """Liveness probe — always returns 200 while the server is up."""
        return jsonify({"status": "ok"})

    @app.get("/api/status")
    def status() -> Response:
        """Return the current DJ state and active track information."""
        orch = _orchestrator()
        track = orch.current_track
        return jsonify(
            {
                "dj_state": orch.dj_state.name,
                "current_track": (
                    {
                        "name": track.name,
                        "artist": track.artist,
                        "remaining_sec": round(track.remaining_sec, 1),
                    }
                    if track
                    else None
                ),
            }
        )

    @app.post("/api/pause")
    def pause() -> Response:
        """
        Pause DJ interrupts.

        .. note::
            Full implementation deferred to Phase 2 (GUI integration).
            Currently a stub that always returns 501.
        """
        return jsonify({"error": "pause not yet implemented"}), 501

    @app.post("/api/resume")
    def resume() -> Response:
        """
        Resume DJ interrupts after a pause.

        .. note::
            Full implementation deferred to Phase 2 (GUI integration).
        """
        return jsonify({"error": "resume not yet implemented"}), 501
