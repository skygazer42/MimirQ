"""
Marker parser (external service).

Marker is an optional heavyweight PDF->Markdown converter. To avoid bloating the
main backend image, we integrate it as an external HTTP service.

Config via env/.env:
- MARKER_ENABLED=true
- MARKER_API_URL=http://localhost:2080/v1/marker/convert  (recommended: full endpoint)
"""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests
from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.utils.zip_processor import ZipImageProcessor
from app.rag.core.logging import get_logger

logger = get_logger("parsing.marker")
_ENDPOINT_MISMATCH_STATUSES = {404, 405, 415, 422}


def _sanitize_run_id(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)[:120] or "marker"
    return text


class MarkerParser:
    """
    Call a Marker-compatible HTTP API and return Markdown output.

    Expected request (default):
    - POST MARKER_API_URL
    - multipart/form-data with field name "file"

    Supported responses (best-effort):
    - application/zip: extract Markdown + images into an artifact directory and return Markdown
    - application/json: read "markdown"/"text"/"content" fields
    - text/*: treat as Markdown directly
    """

    def __init__(self) -> None:
        self._enabled = bool(getattr(settings, "MARKER_ENABLED", False))
        self._api_url = (getattr(settings, "MARKER_API_URL", "") or "").strip()
        self._timeout_sec = float(getattr(settings, "MARKER_TIMEOUT_SEC", 600) or 600)

        if not self._enabled:
            raise RuntimeError("Marker is disabled (MARKER_ENABLED=false).")
        if not self._api_url:
            raise RuntimeError("Marker requires MARKER_API_URL.")

        self._session = requests.Session()

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = _sanitize_run_id(document_id or file_path.stem or "marker")
        return (file_path.parent / ".marker" / run_id).absolute()

    def _candidate_upload_urls(self) -> list[str]:
        """
        Return the configured URL plus known Marker upload-compatible fallbacks.

        Historical docs/config in this repo used `/convert`, but the upstream
        Marker service exposed by `marker_server` currently serves multipart PDF
        uploads at `/marker/upload`.
        """

        raw = self._api_url.strip()
        if not raw:
            return []

        candidates: list[str] = [raw]
        try:
            parts = urlsplit(raw)
        except Exception:
            return candidates

        fallback = urlunsplit((parts.scheme, parts.netloc, "/marker/upload", parts.query, parts.fragment))
        if fallback and fallback not in candidates:
            candidates.append(fallback)
        return candidates

    def _post_multipart(self, *, file_path: Path) -> requests.Response:
        file_bytes = file_path.read_bytes()
        files = {"file": (file_path.name, file_bytes, "application/pdf")}
        # Keep params minimal; servers can ignore unknown fields.
        data = {"output_format": "markdown"}
        candidate_urls = self._candidate_upload_urls()
        last_response: requests.Response | None = None

        for index, url in enumerate(candidate_urls):
            resp = self._session.post(url, files=files, data=data, timeout=self._timeout_sec)
            last_response = resp
            if resp.status_code not in _ENDPOINT_MISMATCH_STATUSES or index == len(candidate_urls) - 1:
                return resp

            logger.warning(
                "[marker] multipart upload endpoint mismatch at %s (status=%s); retrying fallback %s",
                url,
                resp.status_code,
                candidate_urls[index + 1],
            )

        if last_response is None:
            raise RuntimeError("Marker parser requires at least one candidate upload URL.")
        return last_response

    @staticmethod
    def _looks_like_zip(resp: requests.Response) -> bool:
        ctype = str(resp.headers.get("content-type") or "").lower()
        if "application/zip" in ctype or "application/x-zip" in ctype:
            return True
        body = getattr(resp, "content", b"") or b""
        return len(body) >= 4 and body[:2] == b"PK"

    @staticmethod
    def _extract_markdown_from_json(data: Any) -> str:
        if isinstance(data, dict):
            for key in ("markdown", "md", "content", "text", "result", "output"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val
        return ""

    def _handle_zip_response(self, *, resp: requests.Response, artifact_root: Path) -> tuple[str, str | None]:
        artifact_root.mkdir(parents=True, exist_ok=True)

        zip_path = artifact_root / "marker_output.zip"
        zip_path.write_bytes(resp.content or b"")

        extract_root = artifact_root / "output"
        extract_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            ZipImageProcessor._safe_extract(zip_ref, extract_root)

        markdown_files = list(extract_root.rglob("*.md"))
        if not markdown_files:
            # Some servers may return .markdown or .txt.
            markdown_files = list(extract_root.rglob("*.markdown"))
        if not markdown_files:
            return "", str(extract_root)

        md_path = ZipImageProcessor._choose_markdown_file(markdown_files)
        markdown_text = md_path.read_text(encoding="utf-8", errors="ignore")
        return markdown_text, str(md_path.parent)

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

        logger.info("[marker] parsing %s", file_path.name)
        resp = self._post_multipart(file_path=file_path)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise RuntimeError(f"Marker API error {resp.status_code}: {(resp.text or '')[:500]}")

        markdown_text = ""
        asset_base_dir: str | None = None

        if self._looks_like_zip(resp):
            markdown_text, asset_base_dir = self._handle_zip_response(resp=resp, artifact_root=artifact_root)
        else:
            ctype = str(resp.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                try:
                    data = resp.json()
                except Exception:
                    data = json.loads((resp.text or "").strip() or "{}")
                markdown_text = self._extract_markdown_from_json(data)
            else:
                markdown_text = resp.text or ""

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": "pdf",
            "parser_backend": "marker",
            "artifact_dir": str(artifact_root),
        }
        if asset_base_dir:
            metadata["asset_base_dir"] = asset_base_dir
        if dataset_id:
            metadata["dataset_id"] = str(dataset_id)

        return [Document(page_content=markdown_text, metadata=metadata)]
