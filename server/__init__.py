"""Local FastAPI wrapper for the Pixorra core.

The server never mutates core behavior: it serializes snapshots, accepts
whole-file ordered models (per the save contract), and exposes the
SaveSession prepare/commit/reload workflow over HTTP.
"""

from .app import create_app


__all__ = ["create_app"]
