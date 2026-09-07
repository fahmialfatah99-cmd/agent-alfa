"""alfa.dashboard package."""

from alfa.dashboard.app import app, create_app


def get_app():
    """Return the global FastAPI application instance."""
    return app


__all__ = ["app", "get_app", "create_app"]
