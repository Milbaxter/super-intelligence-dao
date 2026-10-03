"""API error type rendered as {"error": {"code", "message", ...}}."""

from __future__ import annotations

import math


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.extra = extra

    def body(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, **self.extra}}


def not_found(what: str, id_: str) -> ApiError:
    return ApiError(404, "not_found", f"{what} {id_!r} not found")


MAX_JSON_DEPTH = 32


def check_json(value, depth: int = 0) -> None:
    """Reject non-finite numbers (NaN/Infinity are accepted by json.loads but break storage, comparisons and
    JSON output for every later reader) and absurdly deep nesting in request bodies."""
    if depth > MAX_JSON_DEPTH:
        raise ApiError(422, "invalid_body", f"JSON nested deeper than {MAX_JSON_DEPTH} levels")
    if isinstance(value, float) and not math.isfinite(value):
        raise ApiError(422, "invalid_body", "NaN/Infinity are not allowed")
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 2**53:
        raise ApiError(422, "invalid_body", "integer out of range")
    if isinstance(value, dict):
        for v in value.values():
            check_json(v, depth + 1)
    elif isinstance(value, list):
        for v in value:
            check_json(v, depth + 1)
