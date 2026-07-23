import json

from fastapi import HTTPException
from starlette.requests import Request

from app.core.exceptions import http_exception_handler
from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": []})


def test_http_exception_handler_hides_server_details_but_keeps_client_details() -> None:
    server_response = http_exception_handler(
        _request(),
        HTTPException(status_code=500, detail="database password leaked"),
    )
    client_response = http_exception_handler(
        _request(),
        HTTPException(status_code=400, detail="invalid profile"),
    )

    assert json.loads(server_response.body)["message"] == "An unexpected error occurred. Please try again later."
    assert json.loads(client_response.body)["message"] == "invalid profile"


def test_retrieval_admission_timeout_is_retryable_service_unavailable() -> None:
    response = http_exception_handler(
        _request(),
        RetrievalAdmissionTimeoutError(2.1),
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "3"
    assert json.loads(response.body)["error"] == "SERVICE_UNAVAILABLE"
