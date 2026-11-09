import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.schemas.document_ingestion import UrlUploadRequest
from app.api.utils.url_ingest import DownloadedURL
from app.services import document_ingestion_sources as sources


@pytest.mark.parametrize("validators", [{"etag": 0}, {"last_modified": False}])
def test_supplied_invalid_http_validator_is_not_changed_into_an_absent_header(validators):
    downloaded = SimpleNamespace(final_url="https://example.test/document.pdf", etag=None, last_modified=None)
    for name, value in validators.items():
        setattr(downloaded, name, value)
    ingest_file = sources.UrlIngestFile(
        file_id=uuid4(), final_path=Path("unused.pdf"), file_ext=".pdf", downloaded=downloaded,
        content_type=None, fetched_at_iso="2026-01-01T00:00:00+00:00", content_sha256="a" * 64,
    )
    with pytest.raises(AttributeError):
        asyncio.run(sources.url_source_metadata(url=downloaded.final_url, ingest_file=ingest_file))


def test_url_ingestion_keeps_an_absent_mime_header_as_none(tmp_path, monkeypatch):
    async def download(url, destination, **kwargs):
        destination.write_bytes(b"document body")
        return DownloadedURL(size_bytes=13, content_type=None, final_url=url)

    monkeypatch.setattr(sources.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(sources, "download_url_to_path", download)
    url = "https://example.test/document.pdf"
    result = asyncio.run(sources.download_url_ingest_file(
        url=url, body=UrlUploadRequest(url=url, filename="document.pdf"), tenant_id=uuid4()
    ))
    assert result.content_type is None
    metadata = asyncio.run(sources.url_source_metadata(url=url, ingest_file=result))
    assert metadata.etag is None
    assert metadata.last_modified_raw is None
