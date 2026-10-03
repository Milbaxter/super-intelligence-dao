"""FastAPI dependencies: per-request DB connection, auth, lease sweep."""

from __future__ import annotations

import hashlib
import hmac
from typing import Iterator

from fastapi import Request

from . import council, db, lifecycle
from .errors import ApiError


def get_conn(request: Request) -> Iterator:
    conn = db.connect(request.app.state.settings.db_path)
    try:
        lifecycle.sweep_expired(conn)
        council.sweep(conn)  # lazy council stage deadlines / reviews (no-op unless something is due)
        yield conn
    finally:
        conn.close()


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def bearer(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip() or None
    return None


def require_contributor(request: Request, conn) -> dict:
    token = bearer(request)
    if not token:
        raise ApiError(401, "unauthorized", "Missing Authorization: Bearer <api_key>")
    h = hash_key(token)
    row = db.one(conn, "SELECT * FROM contributors WHERE api_key_hash=?", (h,))
    if not row or not hmac.compare_digest(row["api_key_hash"], h) or row["status"] != "active":
        raise ApiError(401, "unauthorized", "Invalid or inactive api key")
    return row


def require_steward(request: Request) -> None:
    token = bearer(request) or ""
    key = request.app.state.settings.steward_key
    if not key or not hmac.compare_digest(token.encode(), key.encode()):
        raise ApiError(401, "unauthorized", "Steward key required")
