"""
MimirQ API unified exception handling module
"""
import traceback
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.status import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_413_CONTENT_TOO_LARGE,
    HTTP_422_UNPROCESSABLE_CONTENT,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from app.rag.core.logging import get_logger

logger = get_logger("core.exceptions")

_HINT_BY_KEY: dict[str, str] = {
    "timeout": "Parsing timed out. Try a smaller file, choose a faster parser backend, or increase TASK_JOB_TIMEOUT_SEC.",
    "payload_too_large": "Request payload is too large. Try a smaller file, or increase MAX_FILE_SIZE / REQUEST_MAX_BODY_BYTES.",
    "result_too_large": "Parsing output is too large. Try a smaller file or reduce extracted content (e.g., fewer pages).",
    "parse_failed": "Parsing failed. Try a different parser backend; for scanned PDFs you may need OCR.",
    "preprocess_failed": "Preprocessing failed. Disable file preprocess steps in the ingestion policy or adjust the preprocess config.",
    "rate_limited": "You are being rate limited. Retry later, or reduce concurrent requests / embedding concurrency.",
}


def _derive_hint(
    *,
    status_code: int,
    error_code: str,
    message: str,
    detail: dict[str, Any] | None,
) -> str | None:
    # 1) Explicit hint takes precedence.
    if isinstance(detail, dict):
        raw_hint = detail.get("hint")
        if isinstance(raw_hint, str) and raw_hint.strip():
            return raw_hint.strip()

        hint_key = detail.get("hint_key")
        if isinstance(hint_key, str) and hint_key.strip():
            mapped = _HINT_BY_KEY.get(hint_key.strip().lower())
            if mapped:
                return mapped

    # 2) Heuristics for legacy string-only HTTPException details.
    msg = str(message or "").strip()
    norm = msg.lower()

    if status_code == HTTP_413_CONTENT_TOO_LARGE or "file too large" in norm:
        return _HINT_BY_KEY.get("payload_too_large")

    if status_code == HTTP_429_TOO_MANY_REQUESTS or error_code == "RATE_LIMIT_EXCEEDED":
        return _HINT_BY_KEY.get("rate_limited")

    if "worker_timeout" in norm or "timeout" in norm:
        return _HINT_BY_KEY.get("timeout")

    if "preprocess_failed" in norm:
        return _HINT_BY_KEY.get("preprocess_failed")

    if "parse_failed" in norm or "failed to parse" in norm:
        return _HINT_BY_KEY.get("parse_failed")

    return None


def _sanitize_json(value: Any, *, _depth: int = 0) -> Any:
    """
    Best-effort JSON sanitization for exception payloads.

    Notes:
    - Pydantic v2 validation errors can include non-JSON-serializable objects
      (e.g. `ValueError` instances) inside error `ctx`.
    - Our error responses should never crash while rendering JSON.
    """
    if _depth >= 10:
        return str(value)

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            # Never call user-defined __str__/__repr__ when formatting dict keys; keep
            # the sanitizer itself exception-safe.
            if isinstance(k, (str, int, float, bool, type(None))):
                key = str(k)
            else:
                key = object.__repr__(k)
            out[key] = _sanitize_json(v, _depth=_depth + 1)
        return out

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json(v, _depth=_depth + 1) for v in value]

    # Fallback: stringify unknown objects (exceptions, UUIDs, etc).
    return str(value)


class ErrorResponse(BaseModel):
    error: str
    message: str
    detail: dict[str, Any] | None = None
    request_id: str | None = None
    hint: str | None = None


class MimirQError(Exception):
    """Base exception for MimirQ application."""

    def __init__(
        self,
        message: str,
        error_code: str = "INTERNAL_ERROR",
        status_code: int = HTTP_500_INTERNAL_SERVER_ERROR,
        detail: dict[str, Any] | None = None,
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)

    def to_response(self, request_id: str | None = None) -> ErrorResponse:
        return ErrorResponse(
            error=self.error_code,
            message=self.message,
            detail=self.detail if self.detail else None,
            request_id=request_id,
        )


MimirQException = MimirQError


class ValidationError(MimirQError):
    def __init__(
        self,
        message: str,
        field: str | None = None,
        detail: dict[str, Any] | None = None,
    ):
        merged_detail: dict[str, Any] = dict(detail or {})
        if field:
            merged_detail["field"] = field
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            detail=merged_detail or None,
        )


class NotFoundError(MimirQError):
    def __init__(self, resource: str, identifier: str | None = None):
        detail: dict[str, Any] = {"resource": resource}
        if identifier:
            detail["identifier"] = identifier
        super().__init__(
            message=f"{resource} not found",
            error_code="NOT_FOUND",
            status_code=HTTP_404_NOT_FOUND,
            detail=detail,
        )


class AuthenticationError(MimirQError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR",
            status_code=HTTP_401_UNAUTHORIZED,
        )


class AuthorizationError(MimirQError):
    def __init__(self, message: str = "Permission denied", resource: str | None = None):
        detail: dict[str, Any] = {}
        if resource:
            detail["resource"] = resource
        super().__init__(
            message=message,
            error_code="AUTHORIZATION_ERROR",
            status_code=HTTP_403_FORBIDDEN,
            detail=detail or None,
        )


class RateLimitError(MimirQError):
    def __init__(self, retry_after: float = 60.0):
        super().__init__(
            message="Too many requests. Please try again later.",
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail={"retry_after": retry_after},
        )


class ServiceUnavailableError(MimirQError):
    def __init__(self, service: str, message: str | None = None):
        super().__init__(
            message=message or f"Service '{service}' is temporarily unavailable",
            error_code="SERVICE_UNAVAILABLE",
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail={"service": service},
        )


class LLMError(MimirQError):
    def __init__(self, message: str, provider: str | None = None):
        detail: dict[str, Any] = {}
        if provider:
            detail["provider"] = provider
        super().__init__(
            message=message,
            error_code="LLM_ERROR",
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail or None,
        )


class DocumentProcessingError(MimirQError):
    def __init__(
        self,
        message: str,
        document_id: str | None = None,
        stage: str | None = None,
    ):
        detail: dict[str, Any] = {}
        if document_id:
            detail["document_id"] = document_id
        if stage:
            detail["stage"] = stage
        super().__init__(
            message=message,
            error_code="DOCUMENT_PROCESSING_ERROR",
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            detail=detail or None,
        )


class RetrievalError(MimirQError):
    def __init__(self, message: str, backend: str | None = None):
        detail: dict[str, Any] = {}
        if backend:
            detail["backend"] = backend
        super().__init__(
            message=message,
            error_code="RETRIEVAL_ERROR",
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail or None,
        )


# =============================================================================
# Lightweight RAG Exceptions (no HTTP status codes)
# These are used internally by RAG pipelines and should remain lightweight
# to avoid circular imports.
# =============================================================================

class ExtractError(Exception):
    """Extraction failure."""


class SearchError(Exception):
    """Search failure."""


class AIError(Exception):
    """Generic AI/LLM error."""


class ConfigError(Exception):
    """Configuration missing or invalid."""


class LLMTimeoutError(LLMError):
    """LLM timeout error."""
    def __init__(self, message: str = "LLM request timed out", provider: str | None = None):
        super().__init__(message=message, provider=provider)


class LoadError(Exception):
    """Document load failure."""


class PromptError(Exception):
    """Prompt template error."""


def get_request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-ID") or getattr(request.state, "request_id", None)


def mimirq_exception_handler(request: Request, exc: MimirQError) -> JSONResponse:
    request_id = get_request_id(request)
    logger.warning(
        "MimirQ exception: %s - %s (request_id=%s)",
        exc.error_code,
        exc.message,
        request_id,
    )
    hint = _derive_hint(
        status_code=int(exc.status_code),
        error_code=str(exc.error_code or "INTERNAL_ERROR"),
        message=str(exc.message or ""),
        detail=exc.detail if isinstance(exc.detail, dict) else None,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response(request_id).model_dump(exclude_none=True) | ({"hint": hint} if hint else {}),
    )


def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = get_request_id(request)

    error_code_map = {
        401: "AUTHENTICATION_ERROR",
        403: "AUTHORIZATION_ERROR",
        404: "NOT_FOUND",
        422: "VALIDATION_ERROR",
        413: "PAYLOAD_TOO_LARGE",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }

    error_code = error_code_map.get(exc.status_code, "HTTP_ERROR")
    message = ""
    detail: dict[str, Any] | None = None
    if isinstance(exc.detail, dict):
        detail = dict(exc.detail)
        raw = detail.get("message")
        message = str(raw) if raw is not None else "Request failed"
    elif isinstance(exc.detail, str):
        message = exc.detail
    else:
        message = "Request failed"

    hint = _derive_hint(
        status_code=int(exc.status_code),
        error_code=str(error_code),
        message=str(message),
        detail=detail,
    )

    # Keep detail payload small and stable: promote message/hint to top-level fields.
    if detail is not None:
        detail.pop("message", None)
        detail.pop("hint", None)
        detail.pop("hint_key", None)
        if not detail:
            detail = None

    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content=ErrorResponse(
            error=error_code,
            message=message,
            detail=detail,
            request_id=request_id,
            hint=hint,
        ).model_dump(exclude_none=True),
    )


def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = get_request_id(request)
    errors = _sanitize_json(exc.errors())
    # FastAPI default 422 payload is a list under "detail"; keep it available for callers.
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_CONTENT,
        content=ErrorResponse(
            error="VALIDATION_ERROR",
            message="Validation error",
            detail={"errors": errors},
            request_id=request_id,
        ).model_dump(exclude_none=True),
    )


def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = get_request_id(request)
    logger.error(
        "Unhandled exception (request_id=%s): %s\n%s",
        request_id,
        str(exc),
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="INTERNAL_ERROR",
            message="An unexpected error occurred. Please try again later.",
            request_id=request_id,
        ).model_dump(exclude_none=True),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MimirQError, mimirq_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
