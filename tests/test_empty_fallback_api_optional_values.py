import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.utils.url_ingest import _redirect_url, _save_download_response
from app.api.v1.integrations.dify_support.external_api import _request_client_ip


def test_absent_client_ip_stays_optional() -> None:
    assert _request_client_ip(Request({"type": "http", "headers": [], "client": None})) is None
    assert _request_client_ip(Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)})) == "127.0.0.1"


@pytest.mark.asyncio
async def test_download_metadata_preserves_missing_and_present_empty_headers(tmp_path) -> None:
    response = httpx.Response(200, headers={"etag": "", "last-modified": ""})
    result = await _save_download_response(
        response, destination=tmp_path / "empty.bin", max_bytes=1, final_url="https://example.com"
    )
    assert result.etag == ""
    assert result.last_modified == ""
    absent = await _save_download_response(
        httpx.Response(200), destination=tmp_path / "absent.bin", max_bytes=1, final_url="https://example.com"
    )
    assert absent.etag is None
    assert absent.last_modified is None


def test_missing_redirect_location_keeps_the_existing_client_error() -> None:
    with pytest.raises(HTTPException) as error:
        _redirect_url(
            httpx.Response(302), request_url="https://example.com", follow_redirects=True, redirects_remaining=1
        )
    assert error.value.status_code == 400
