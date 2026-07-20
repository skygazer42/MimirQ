import json

from fastapi import HTTPException
from starlette.requests import Request

from app.core.exceptions import http_exception_handler


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
