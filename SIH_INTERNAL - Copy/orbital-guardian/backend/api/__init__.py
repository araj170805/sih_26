"""
backend.api package.

`app.py` holds the FastAPI application; routers live in
sibling modules. Re-exported here so both
`from backend.api import app` and
`uvicorn backend.api:app` keep working.
"""

from .app import app  # noqa: F401
