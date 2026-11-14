"""
PaddleOCR-VL parser (external service).

PaddleOCR-VL is an optional heavyweight OCR/layout pipeline. To avoid bloating
the main backend image, we integrate it as an external HTTP service.

Config via env/.env:
- PADDLE_VL_ENABLED=true
- PADDLE_VL_API_URL=http://localhost:9030/convert  (your service endpoint)
"""

import json
import re
import zipfile
from pathlib import Path
from typing import Any

import requests
from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.parsers.response_text import extract_markdown_from_json as _extract_markdown_from_json
from app.parsing.utils.artifact_normalizer import normalize_extracted_artifacts
from app.parsing.utils.zip_processor import process_zip_with_images, safe_extract_zip
from app.rag.core.logging import get_logger

from .service_url_fallback import build_docker_service_url_candidates

logger = get_logger("parsing.paddle_vl")


def _sanitize_run_id(value: str) -> str:
    text = (value).strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)[:120] or "paddlevl"
    return text


def _looks_like_zip(resp: requests.Response) -> bool:
    ctype = str(resp.headers.get("content-type") or "").lower()
    if "application/zip" in ctype or "application/x-zip" in ctype:
        return True
    body = getattr(resp, "content", b"") or b""
    return len(body) >= 4 and body[:2] == b"PK"


class PaddleVLParser:
    """
    Call a PaddleOCR-VL-compatible HTTP API and return Markdown output.

    The service is expected to accept multipart/form-data with field name "file"
    and return either:
    - ZIP (recommended): a folder structure with page_* directories and Markdown,
      which will be normalized to a stable layout under `images/` + `result.md`.
    - JSON: with "markdown"/"text"/"content" fields.
    - text/*: markdown directly.
    """

    def __init__(self) -> None:
        self._enabled = settings.PADDLE_VL_ENABLED
        self._api_url = settings.PADDLE_VL_API_URL.strip()
        self._timeout_sec = float(settings.PADDLE_VL_TIMEOUT_SEC or 600)

        if not self._enabled:
            raise RuntimeError("PaddleOCR-VL is disabled (PADDLE_VL_ENABLED=false).")
        if not self._api_url:
            raise RuntimeError("PaddleOCR-VL requires PADDLE_VL_API_URL.")

        self._session = requests.Session()

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = _sanitize_run_id(document_id or file_path.stem or "paddlevl")
        return (file_path.parent / ".paddlevl" / run_id).absolute()

    def _post_multipart(self, *, file_path: Path) -> requests.Response:
        file_bytes = file_path.read_bytes()
        files = {"file": (file_path.name, file_bytes, "application/pdf")}
        data = {"output_format": "markdown"}
        candidate_urls = build_docker_service_url_candidates(
            self._api_url,
            service_hostnames={"mimirq-paddlevl"},
        )
        for index, url in enumerate(candidate_urls):
            try:
                return self._session.post(url, files=files, data=data, timeout=self._timeout_sec)
            except requests.RequestException as exc:
                if index == len(candidate_urls) - 1:
                    raise
                logger.warning(
                    "[paddle_vl] request to %s failed (%s); retrying fallback %s",
                    url,
                    exc.__class__.__name__,
                    candidate_urls[index + 1],
                )
        raise RuntimeError("PaddleOCR-VL parser requires at least one candidate API URL.")

    def _handle_zip_response(
        self,
        *,
        resp: requests.Response,
        artifact_root: Path,
        dataset_id: str | None,
        document_id: str | None,
        tenant_id: str | None,
    ) -> tuple[str, str | None]:
        artifact_root.mkdir(parents=True, exist_ok=True)

        zip_path = artifact_root / "paddlevl_output.zip"
        zip_path.write_bytes(resp.content or b"")

        # When object storage is enabled and we have stable identifiers, upload images to MinIO and
        # Rewrite Markdown and HTML image refs to signed/public URLs.
        if settings.MINIO_ENABLED and dataset_id and document_id:
            out = process_zip_with_images(
                zip_path=zip_path,
                dataset_id=str(dataset_id),
                document_id=str(document_id),
                tenant_id=tenant_id,
            )
            return out["markdown"], None

        extract_root = artifact_root / "output"
        extract_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            safe_extract_zip(zip_ref, extract_root)

        # Normalize extracted artifacts into a stable layout under extract_root:
        # - result.md at root
        # - images/ at root (optional)
        try:
            normalized = normalize_extracted_artifacts(extract_root)
        except Exception as exc:
            logger.warning("[paddle_vl] artifact normalize failed: %s", str(exc)[:200])
            return "", str(extract_root)

        md_path = normalized["markdown_file"]
        if md_path is not None and md_path.exists():
            return md_path.read_text(encoding="utf-8", errors="ignore"), str(extract_root)

        return "", str(extract_root)

    def parse(
        self,
        file_path: Path,
        *,
        dataset_id: str | None = None,  # kept for interface parity
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

        logger.info("[paddle_vl] parsing %s", file_path.name)
        resp = self._post_multipart(file_path=file_path)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise RuntimeError(f"PaddleOCR-VL API error {resp.status_code}: {(resp.text)[:500]}")

        markdown_text = ""
        asset_base_dir: str | None = None

        if _looks_like_zip(resp):
            markdown_text, asset_base_dir = self._handle_zip_response(
                resp=resp,
                artifact_root=artifact_root,
                dataset_id=dataset_id,
                document_id=document_id,
                tenant_id=tenant_id,
            )
        else:
            ctype = str(resp.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                try:
                    data = resp.json()
                except Exception:
                    data = json.loads((resp.text).strip() or "{}")
                markdown_text = _extract_markdown_from_json(data)
            else:
                markdown_text = resp.text

        # If object storage is disabled, strip image references to avoid dead links after artifact cleanup.
        if not settings.MINIO_ENABLED and markdown_text:
            markdown_text = re.sub(r"!\[[^\]]*\]\(\s*[^)\s]+?\s*\)\s*", "", markdown_text)
            markdown_text = re.sub(r"<img[^>]*?>", "", markdown_text, flags=re.IGNORECASE)

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": "pdf",
            "parser_backend": "paddle_vl",
            "element_kind": "paragraph",
            "element_text": markdown_text,
            "element_attributes": {
                "source_content_type": "text",
                "source_doc_type": "paragraph",
            },
            "artifact_dir": str(artifact_root),
        }
        if asset_base_dir:
            metadata["asset_base_dir"] = asset_base_dir
        if dataset_id:
            metadata["dataset_id"] = str(dataset_id)

        return [Document(page_content=markdown_text, metadata=metadata)]
