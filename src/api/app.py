"""Flask application factory."""

from __future__ import annotations

from flask import Flask

from src.api.routes import register_routes
from src.core.orchestrator import RadioDJOrchestrator


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
    app = Flask(__name__)
    app.extensions["orchestrator"] = orchestrator
    register_routes(app)
    return app
