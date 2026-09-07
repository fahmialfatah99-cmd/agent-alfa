"""alfa.dashboard package."""

def __getattr__(name: str):
    if name == "app":
        from alfa.dashboard.app import app
        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["app"]
