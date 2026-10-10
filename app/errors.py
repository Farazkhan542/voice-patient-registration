"""API error type and the { "data": ..., "error": ... } response envelope."""

from typing import Any

from pydantic import ValidationError


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: list | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or []


def ok(data: Any) -> dict:
    return {"data": data, "error": None}


def fail(code: str, message: str, details: list | None = None) -> dict:
    return {"data": None, "error": {"code": code, "message": message, "details": details or []}}


def field_errors(errors: list[dict]) -> list[dict]:
    """Flatten Pydantic errors into [{field, message}], dropping transport prefixes."""
    result = []
    for err in errors:
        location = [str(part) for part in err.get("loc", ()) if part not in ("body", "query", "path")]
        message = str(err.get("msg", "invalid value")).removeprefix("Value error, ")
        result.append({"field": ".".join(location) or "body", "message": message})
    return result


def validation_details(exc: ValidationError) -> list[dict]:
    return field_errors(exc.errors())
