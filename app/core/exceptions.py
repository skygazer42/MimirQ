"""
MimirQ API unified exception handling module
"""
import logging
import traceback
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.status import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)

# Starlette exposes `HTTP_422_UNPROCESSABLE_ENTITY` (422). Some codebases refer to
# a non-standard `HTTP_422_UNPROCESSABLE_CONTENT` name; keep a compatibility alias.
try:
    from starlette.status import HTTP_422_UNPROCESSABLE_CONTENT  # type: ignore
except ImportError:  # pragma: no cover
    from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY as HTTP_422_UNPROCESSABLE_CONTENT

logger = logging.getLogger(__name__)


class ErrorResponse(BaseModel):
    error: str
    message: str
    detail: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None


class MimirQError(Exception):
    """Base exception for MimirQ application."""

    def __init__(
        self,
        message: str,
        error_code: str = "INTERNAL_ERROR",
        status_code: int = HTTP_500_INTERNAL_SERVER_ERROR,
        detail: Optional[Dict[str, Any]] = None,
    ):
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)

    def to_response(self, request_id: Optional[str] = None) -> ErrorResponse:
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
        field: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ):
        merged_detail: Dict[str, Any] = dict(detail or {})
        if field:
            merged_detail["field"] = field
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            detail=merged_detail or None,
        )


class NotFoundError(MimirQError):
    def __init__(self, resource: str, identifier: Optional[str] = None):
        detail: Dict[str, Any] = {"resource": resource}
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
    def __init__(self, message: str = "Permission denied", resource: Optional[str] = None):
        detail: Dict[str, Any] = {}
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
    def __init__(self, service: str, message: Optional[str] = None):
        super().__init__(
            message=message or f"Service '{service}' is temporarily unavailable",
            error_code="SERVICE_UNAVAILABLE",
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail={"service": service},
        )


class LLMError(MimirQError):
    def __init__(self, message: str, provider: Optional[str] = None):
        detail: Dict[str, Any] = {}
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
        document_id: Optional[str] = None,
        stage: Optional[str] = None,
    ):
        detail: Dict[str, Any] = {}
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
    def __init__(self, message: str, backend: Optional[str] = None):
        detail: Dict[str, Any] = {}
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
    def __init__(self, message: str = "LLM request timed out", provider: Optional[str] = None):
        super().__init__(message=message, provider=provider)


class LoadError(Exception):
    """Document load failure."""


class PromptError(Exception):
    """Prompt template error."""


def get_request_id(request: Request) -> Optional[str]:
    return request.headers.get("X-Request-ID") or getattr(request.state, "request_id", None)


async def mimirq_exception_handler(request: Request, exc: MimirQError) -> JSONResponse:
    request_id = get_request_id(request)
    logger.warning(
        "MimirQ exception: %s - %s (request_id=%s)",
        exc.error_code,
        exc.message,
        request_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response(request_id).model_dump(exclude_none=True),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = get_request_id(request)

    error_code_map = {
        401: "AUTHENTICATION_ERROR",
        403: "AUTHORIZATION_ERROR",
        404: "NOT_FOUND",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }

    error_code = error_code_map.get(exc.status_code, "HTTP_ERROR")
    message = str(exc.detail) if isinstance(exc.detail, str) else "Request failed"
    detail = exc.detail if isinstance(exc.detail, dict) else None

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=error_code,
            message=message,
            detail=detail,
            request_id=request_id,
        ).model_dump(exclude_none=True),
    )


async def request_validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = get_request_id(request)
    # FastAPI default 422 payload is a list under "detail"; keep it available for callers.
    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_CONTENT,
        content=ErrorResponse(
            error="VALIDATION_ERROR",
            message="Validation error",
            detail={"errors": exc.errors()},
            request_id=request_id,
        ).model_dump(exclude_none=True),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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
