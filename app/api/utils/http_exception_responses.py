"""Shared FastAPI response metadata for routes with the exact same contract."""

DEFAULT_HTTP_EXCEPTION_RESPONSES: dict[int, dict[str, str]] = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

__all__ = ["DEFAULT_HTTP_EXCEPTION_RESPONSES"]
