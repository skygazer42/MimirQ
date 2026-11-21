from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas.documents.ingestion import LocalHtmlIngestRequest, UrlUploadRequest
from app.api.utils.url_ingest import DownloadedURL, ValidatedFetchTarget
from app.services.documents import source_acquisition as sources


@pytest.mark.asyncio
async def test_rejected_download_extension_removes_the_unregistered_temp_file(monkeypatch, tmp_path: Path):
    async def download(target, destination, **kwargs):
        destination.write_bytes(b"content")
        return DownloadedURL(size_bytes=7, content_type="text/plain", final_url=target.raw)

    monkeypatch.setattr(sources.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(sources.settings, "ALLOWED_EXTENSIONS", ".txt")
    monkeypatch.setattr(sources, "download_url_to_path", download)
    with pytest.raises(HTTPException) as caught:
        await sources.download_url_ingest_file(
            target=ValidatedFetchTarget(
                "https://example.com/source", "https://93.184.216.34/source", "example.com", "example.com"
            ),
            body=UrlUploadRequest(url="https://example.com/source", filename="unsafe.exe"),
            tenant_id=uuid4(),
        )
    assert caught.value.status_code == 400
    assert list(tmp_path.rglob("*.urltmp")) == []


def test_partial_html_write_failure_removes_the_unregistered_file(monkeypatch, tmp_path: Path):
    original_write = Path.write_bytes

    def interrupted_write(path, data):
        original_write(path, b"partial")
        raise OSError("write interrupted")

    monkeypatch.setattr(sources.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(sources.settings, "ALLOWED_EXTENSIONS", ".html")
    monkeypatch.setattr(Path, "write_bytes", interrupted_write)
    with pytest.raises(HTTPException) as caught:
        sources.write_local_html_ingest_file(
            body=LocalHtmlIngestRequest(html="<html>content</html>"), tenant_id=uuid4()
        )
    assert caught.value.status_code == 500
    assert list(tmp_path.rglob("*.html")) == []
