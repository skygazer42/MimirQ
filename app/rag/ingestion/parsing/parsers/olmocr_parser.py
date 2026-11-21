"""
olmOCR parser (external service).

olmOCR is an optional heavyweight PDF->Markdown OCR converter. To avoid bloating
the main backend image, we integrate it as an external HTTP service.

Config via env/.env:
- OLMOCR_ENABLED=true
- OLMOCR_API_URL=http://localhost:2085/convert  (recommended: full endpoint)
"""

import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.ingestion.parsing.parsers.response_text import extract_markdown_from_json as _extract_markdown_from_json
from app.rag.ingestion.parsing.utils.artifact_normalizer import sanitize_artifact_run_id

from .service_url_fallback import build_docker_service_url_candidates

logger = logging.getLogger("parsing.olmocr")


class OlmocrParser:
    """
    Call an olmOCR-compatible HTTP API and return Markdown output.

    Expected request (default):
    - POST OLMOCR_API_URL
    - multipart/form-data with field name "file"

    Supported responses (best-effort):
    - application/json: read "markdown"/"text"/"content" fields
    - text/*: treat as Markdown directly
    """

    def __init__(self) -> None:
        self._enabled = settings.OLMOCR_ENABLED
        self._api_url = settings.OLMOCR_API_URL.strip()
        self._timeout_sec = settings.OLMOCR_TIMEOUT_SEC

        if not self._enabled:
            raise RuntimeError("olmOCR is disabled (OLMOCR_ENABLED=false).")
        if not self._api_url:
            raise RuntimeError("olmOCR requires OLMOCR_API_URL.")

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = sanitize_artifact_run_id(document_id or file_path.stem or "olmocr", fallback="olmocr")
        return (file_path.parent / ".olmocr" / run_id).absolute()

    def _post_multipart(self, *, file_path: Path) -> requests.Response:
        suffix = (file_path.suffix).lower()
        content_type = "application/pdf" if suffix == ".pdf" else "application/octet-stream"
        data = {"output_format": "markdown"}
        candidate_urls = build_docker_service_url_candidates(
            self._api_url,
            service_hostnames={"mimirq-olmocr"},
        )
        with requests.Session() as session, file_path.open("rb") as file_handle:
            files = {"file": (file_path.name, file_handle, content_type)}
            for index, url in enumerate(candidate_urls):
                file_handle.seek(0)
                try:
                    return session.post(url, files=files, data=data, timeout=self._timeout_sec)
                except requests.RequestException as exc:
                    if index == len(candidate_urls) - 1:
                        raise
                    logger.warning(
                        "[olmocr] request to %s failed (%s); retrying fallback %s",
                        urlsplit(url).netloc.rsplit("@", 1)[-1],
                        exc.__class__.__name__,
                        urlsplit(candidate_urls[index + 1]).netloc.rsplit("@", 1)[-1],
                    )
        raise RuntimeError("olmOCR parser requires at least one candidate API URL.")

    def parse(
        self,
        file_path: Path,
        *,
        dataset_id: str | None = None,
        document_id: str | None = None,
        tenant_id: str | None = None,  # noqa: ARG002 - reserved for future use
        pdf_quality: dict[str, Any] | None = None,  # noqa: ARG002 - reserved for future use
        **_kwargs,
    ) -> list[Document]:
        _ = (dataset_id, tenant_id, pdf_quality)
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        artifact_root = self._build_artifact_root(file_path, document_id)

        logger.info("[olmocr] parsing %s", file_path.name)
        markdown_text = ""
        with self._post_multipart(file_path=file_path) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"olmOCR API error {resp.status_code}: {resp.text[:500]}")
            ctype = str(resp.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                markdown_text = _extract_markdown_from_json(resp.json())
            elif "application/zip" in ctype or "application/x-zip" in ctype:
                raise RuntimeError("olmOCR API returned unsupported ZIP output")
            else:
                markdown_text = resp.text

        if not markdown_text.strip():
            raise RuntimeError("olmOCR API returned no Markdown content")

        try:
            artifact_root.mkdir(parents=True, exist_ok=True)
            (artifact_root / "result.md").write_text(markdown_text, encoding="utf-8")
        except OSError as exc:
            # Best-effort only; do not block parsing.
            logger.debug("Failed to write olmOCR parse artifact; continuing: %s", exc)

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": "pdf",
            "parser_backend": "olmocr",
            "artifact_dir": str(artifact_root),
        }
        if dataset_id:
            metadata["dataset_id"] = str(dataset_id)

        return [Document(page_content=markdown_text, metadata=metadata)]
