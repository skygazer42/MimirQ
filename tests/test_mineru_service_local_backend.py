from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.services import mineru_service as mineru_service_module
from app.services.mineru_service import mineru_service


@pytest.mark.asyncio
async def test_local_mineru_uses_configured_vlm_http_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%mineru-vlm\n")

    monkeypatch.setattr(settings, "MINERU_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINERU_LOCAL_SERVER_URL", "http://mineru-api:30001", raising=False)
    monkeypatch.setattr(settings, "MINERU_BACKEND", "vlm-http-client", raising=False)
    monkeypatch.setattr(settings, "MINERU_VL_SERVER", "http://mineru-vlm:30002", raising=False)

    captured: dict[str, object] = {}

    class _Response:
        headers = {"Content-Type": "application/zip"}
        content = b"fake-zip"

        async def aclose(self) -> None:
            return None

    class _Pool:
        async def request_with_retry(self, method: str, url: str, **kwargs):  # noqa: ANN001
            captured.update({"method": method, "url": url, **kwargs})
            return _Response()

    monkeypatch.setattr(mineru_service_module, "get_http_client_pool", lambda: _Pool())
    monkeypatch.setattr(
        mineru_service,
        "_documents_from_zip_bytes",
        lambda **_kwargs: [Document(page_content="ok", metadata={"parser_backend": "mineru"})],
    )

    docs = await mineru_service.aparse_file_local(file_path=pdf_path)

    assert docs[0].page_content == "ok"
    assert captured["url"] == "http://mineru-api:30001/file_parse"
    data = captured["data"]
    assert isinstance(data, dict)
    assert data["backend"] == "vlm-http-client"
    assert data["server_url"] == "http://mineru-vlm:30002"


@pytest.mark.asyncio
async def test_local_mineru_defaults_to_pipeline_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%mineru-pipeline\n")

    monkeypatch.setattr(settings, "MINERU_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MINERU_LOCAL_SERVER_URL", "http://mineru-api:30001", raising=False)
    monkeypatch.setattr(settings, "MINERU_BACKEND", "", raising=False)
    monkeypatch.setattr(settings, "MINERU_VL_SERVER", "http://mineru-vlm:30002", raising=False)

    captured: dict[str, object] = {}

    async def _closeable_response_aclose() -> None:
        return None

    class _Response:
        headers = {"Content-Type": "application/zip"}
        content = b"fake-zip"
        aclose = staticmethod(_closeable_response_aclose)

    class _Pool:
        async def request_with_retry(self, method: str, url: str, **kwargs):  # noqa: ANN001
            captured.update({"method": method, "url": url, **kwargs})
            return _Response()

    monkeypatch.setattr(mineru_service_module, "get_http_client_pool", lambda: _Pool())
    monkeypatch.setattr(
        mineru_service,
        "_documents_from_zip_bytes",
        lambda **_kwargs: [Document(page_content="ok", metadata={"parser_backend": "mineru"})],
    )

    await mineru_service.aparse_file_local(file_path=pdf_path)

    data = captured["data"]
    assert isinstance(data, dict)
    assert data["backend"] == "pipeline"
    assert "server_url" not in data
