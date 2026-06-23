"""Flask application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from src.api.routes import register_routes
from src.core.orchestrator import RadioDJOrchestrator

_HERE = Path(__file__).resolve().parent


def create_app(orchestrator: RadioDJOrchestrator) -> Flask:
    """
    Create and configure the Flask application.

    The *orchestrator* is stored in ``app.extensions`` so routes can
    retrieve it without relying on globals.

    Args:
        orchestrator: Running :class:`RadioDJOrchestrator` instance.

    Returns:
        Configured Flask application.
    """
    app = Flask(
        __name__,
        static_folder=str(_HERE / "static"),
        template_folder=str(_HERE / "templates"),
    )
    app.extensions["orchestrator"] = orchestrator
    register_routes(app)
    return app
