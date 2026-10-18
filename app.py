"""Canonical Flask entrypoint for Vercel.

Vercel automatically detects Flask applications exposed as ``app`` from a
root-level ``app.py``.  The implementation remains in ``api.parse`` so the
local API and the deployed function use the same application instance.
"""

from api.parse import app

__all__ = ["app"]
