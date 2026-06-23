"""REST API route definitions and SSE endpoint."""

from __future__ import annotations

import queue

from flask import Flask, Response, current_app, jsonify, render_template, request

from src.core.orchestrator import RadioDJOrchestrator


def _orchestrator() -> RadioDJOrchestrator:
    return current_app.extensions["orchestrator"]


def _track_dict(track) -> dict | None:
    if track is None:
        return None
    return {
        "name": track.name,
        "artist": track.artist,
        "album_art_url": getattr(track, "album_art_url", ""),
        "duration_ms": track.duration_ms,
        "progress_ms": track.progress_ms,
        "remaining_sec": round(track.remaining_sec, 1),
    }


def register_routes(app: Flask) -> None:
    """Attach all API routes to *app*."""

    @app.get("/")
    def index() -> str:
        """Serve the Midnight Radio web UI."""
        return render_template("index.html")

    @app.get("/api/health")
    def health() -> Response:
        """Liveness probe — always returns 200 while the server is up."""
        return jsonify({"status": "ok"})

    @app.get("/api/status")
    def status() -> Response:
        """Return the current DJ state, track info, and last monologue."""
        orch = _orchestrator()
        return jsonify(
            {
                "dj_state": orch.dj_state.name,
                "current_track": _track_dict(orch.current_track),
                "next_track": _track_dict(orch.next_track),
                "last_monologue": orch.last_monologue,
            }
        )

    @app.get("/api/settings")
    def get_settings() -> Response:
        """Return live broadcast settings controlled by the web UI."""
        return jsonify(_orchestrator().runtime_settings)

    @app.patch("/api/settings")
    def patch_settings() -> Response:
        """Apply live broadcast settings controlled by the web UI."""
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON object expected"}), 400

        try:
            settings = _orchestrator().update_runtime_settings(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        return jsonify(settings)

    @app.get("/api/news/latest")
    def latest_news() -> Response:
        """Return article links from the latest top-of-hour news fetch."""
        orch = _orchestrator()
        payload = orch.latest_news_links()
        if not payload.get("articles"):
            payload = orch.refresh_news_links()
        return jsonify(payload)

    @app.get("/api/events")
    def events() -> Response:
        """
        Server-Sent Events stream.

        Each connected client gets its own queue.  The orchestrator
        pushes events (state, track, monologue) which are relayed here.
        """
        orch = _orchestrator()
        client_queue = orch.register_sse_client()

        def generate():
            try:
                while True:
                    try:
                        payload = client_queue.get(timeout=30)
                        yield payload
                    except queue.Empty:
                        # Send keepalive comment to prevent proxy timeouts.
                        yield ": keepalive\n\n"
            except GeneratorExit:
                pass
            finally:
                orch.unregister_sse_client(client_queue)

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/pause")
    def pause() -> Response:
        """Pause DJ interrupts."""
        settings = _orchestrator().update_runtime_settings({"dj_enabled": False})
        return jsonify(settings)

    @app.post("/api/resume")
    def resume() -> Response:
        """Resume DJ interrupts after a pause."""
        settings = _orchestrator().update_runtime_settings({"dj_enabled": True})
        return jsonify(settings)
