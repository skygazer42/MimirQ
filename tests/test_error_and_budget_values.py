import json

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.infrastructure.exceptions import MimirQError, mimirq_exception_handler


@pytest.mark.parametrize("detail", [{}, {"attempts": 0, "retryable": False}, None])
def test_business_error_preserves_supplied_detail_through_http_response(detail) -> None:
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    error = MimirQError("invalid operation", error_code="INVALID_OPERATION", status_code=400, detail=detail)

    response = mimirq_exception_handler(request, error)
    body = json.loads(response.body)

    assert response.status_code == 400
    assert body["message"] == "invalid operation"
    if detail is None:
        assert "detail" not in body
    else:
        assert body["detail"] == detail


@pytest.mark.parametrize("detail", [0, False])
def test_business_error_exposes_an_invalid_detail_type(detail) -> None:
    error = MimirQError("invalid operation", detail=detail)

    with pytest.raises(ValidationError):
        error.to_response()


def test_validation_error_preserves_an_explicit_empty_detail_and_field() -> None:
    from app.infrastructure.exceptions import ValidationError as ApplicationValidationError

    response = ApplicationValidationError("invalid", field="", detail={}).to_response()

    assert response.detail == {"field": ""}


@pytest.mark.parametrize("detail", [0, False])
def test_validation_error_exposes_invalid_detail_types(detail) -> None:
    from app.infrastructure.exceptions import ValidationError as ApplicationValidationError

    with pytest.raises(TypeError):
        ApplicationValidationError("invalid", detail=detail)


def test_llm_error_preserves_an_explicit_empty_provider() -> None:
    from app.infrastructure.exceptions import LLMError

    assert LLMError("failed", provider="").to_response().detail == {"provider": ""}
