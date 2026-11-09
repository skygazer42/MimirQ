import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.utils.url_ingest import _download_result, _validated_redirect_url
from app.api.v1.dify_support.external_api import _request_client_ip
from app.core.cost_tracker import build_cost_event


def test_absent_client_ip_stays_optional() -> None:
    assert _request_client_ip(Request({"type": "http", "headers": [], "client": None})) is None
    assert _request_client_ip(Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)})) == "127.0.0.1"


@pytest.mark.parametrize("value", [0, False, ""])
def test_cost_metadata_preserves_supplied_scalar_values(value) -> None:
    event = build_cost_event(provider="provider", model="model", stage=value)
    assert event["stage"] == str(value)
    assert build_cost_event(provider="provider", model="model")["stage"] is None


def test_download_metadata_preserves_missing_and_present_empty_headers() -> None:
    response = httpx.Response(200, headers={"etag": "", "last-modified": ""})
    result = _download_result(response, size_bytes=0, final_url="https://example.com")
    assert result.etag == ""
    assert result.last_modified == ""
    absent = _download_result(httpx.Response(200), size_bytes=0, final_url="https://example.com")
    assert absent.etag is None
    assert absent.last_modified is None


@pytest.mark.asyncio
async def test_missing_redirect_location_keeps_the_existing_client_error() -> None:
    with pytest.raises(HTTPException) as error:
        await _validated_redirect_url(
            httpx.Response(302), request_url="https://example.com", follow=True, hops=0, max_redirects=1
        )
    assert error.value.status_code == 400
