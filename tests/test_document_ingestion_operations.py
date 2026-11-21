import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas.documents.ingestion import LocalHtmlIngestRequest, UrlUploadRequest
from app.api.utils.url_ingest import ValidatedFetchTarget
from app.models.datasets.records import Dataset
from app.services.documents import ingestion as operations
from app.services.documents import source_acquisition as sources
from app.services.documents.source_persistence import SourceFileLease


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["url", "html"])
async def test_ingestion_policy_failure_cleans_the_acquired_unregistered_source(monkeypatch, tmp_path: Path, origin):
    error = HTTPException(status_code=400, detail="invalid ingestion policy")
    tenant_id = uuid4()
    monkeypatch.setattr(operations.settings, "URL_INGEST_ENABLED", True)
    monkeypatch.setattr(operations.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(operations.settings, "ALLOWED_EXTENSIONS", ".html,.txt")
    monkeypatch.setattr(
        operations.dataset_service,
        "resolve_writable_dataset",
        lambda *args: Dataset(id=uuid4(), tenant_id=tenant_id, dataset_metadata={}),
    )

    def invalid_policy(**kwargs):
        raise error

    async def validate(url) -> ValidatedFetchTarget:
        return _validated_target(url)

    async def download(target: ValidatedFetchTarget, destination, **kwargs):
        from app.api.utils.url_ingest import DownloadedURL

        destination.write_text("content", encoding="utf-8")
        return DownloadedURL(size_bytes=7, content_type="text/plain", final_url=target.raw)

    monkeypatch.setattr(operations, "_prepare_document_ingestion", invalid_policy)
    monkeypatch.setattr(operations, "validate_fetch_target", validate)
    monkeypatch.setattr(sources, "download_url_to_path", download)
    monkeypatch.setattr(sources, "SourceFileLease", SourceFileLease)
    with pytest.raises(HTTPException) as caught:
        if origin == "url":
            await operations.ingest_url(
                body=UrlUploadRequest(url="https://example.com/source.txt"),
                background_tasks=None,
                tenant_id=tenant_id,
                account_id="owner",
                db=object(),
            )
        else:
            await operations.ingest_html(
                body=LocalHtmlIngestRequest(html="<html>content</html>"),
                background_tasks=None,
                tenant_id=tenant_id,
                account_id="owner",
                db=object(),
            )
    assert caught.value is error
    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


def test_document_ingestion_service_resolves_a_dataset_without_importing_api_assembler():
    code = """
import importlib.abc
import sys
from uuid import uuid4

class NoDocumentAssembler(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'app.api.v1.documents.routes':
            raise AssertionError("document ingestion imported the API assembler")
sys.meta_path.insert(0, NoDocumentAssembler())

from app.services.documents import ingestion as document_ingestion

tenant_id, dataset_id = uuid4(), uuid4()
dataset = object()
document_ingestion.dataset_service.get_dataset = lambda db, tenant, current: dataset
document_ingestion.dataset_service.assert_dataset_writable = lambda *args: None
assert document_ingestion.dataset_service.resolve_writable_dataset(object(), tenant_id, "owner", dataset_id) is dataset
assert 'app.api.v1.documents.routes' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stderr


def _validated_target(url: str) -> ValidatedFetchTarget:
    parsed = urlsplit(url)
    return ValidatedFetchTarget(
        raw=url,
        connect_url=parsed._replace(netloc="93.184.216.34").geturl(),
        host=parsed.hostname,
        host_header=parsed.netloc,
    )
