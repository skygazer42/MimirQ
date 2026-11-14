"""
Qianfan-OCR parser (external service).

Qianfan-OCR is integrated as an external HTTP service to keep heavyweight model
runtime dependencies out of the main backend image.

Config via env/.env:
- QIANFAN_OCR_ENABLED=true
- QIANFAN_OCR_API_URL=http://localhost:2090/convert
- QIANFAN_OCR_TIMEOUT_SEC=1800
- QIANFAN_OCR_LAYOUT_AS_THOUGHT=false
"""

import json
import re
from pathlib import Path
from typing import Any

import requests
from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.parsers.response_text import extract_markdown_from_json as _extract_markdown_from_json
from app.rag.core.logging import get_logger

logger = get_logger("parsing.qianfan_ocr")


def _sanitize_run_id(value: str) -> str:
    text = (value).strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)[:120] or "qianfan_ocr"
    return text


class QianfanOCRParser:
    """
    Call a Qianfan-OCR-compatible HTTP API and return Markdown output.

    Expected request:
    - POST QIANFAN_OCR_API_URL
    - multipart/form-data with field name "file"

    Supported responses (best-effort):
    - application/json: read "markdown"/"text"/"content" fields
    - text/*: treat as Markdown directly
    """

    def __init__(self) -> None:
        self._enabled = settings.QIANFAN_OCR_ENABLED
        self._api_url = settings.QIANFAN_OCR_API_URL.strip()
        self._timeout_sec = float(settings.QIANFAN_OCR_TIMEOUT_SEC or 1800)
        self._layout_as_thought = settings.QIANFAN_OCR_LAYOUT_AS_THOUGHT

        if not self._enabled:
            raise RuntimeError("Qianfan-OCR is disabled (QIANFAN_OCR_ENABLED=false).")
        if not self._api_url:
            raise RuntimeError("Qianfan-OCR requires QIANFAN_OCR_API_URL.")

        self._session = requests.Session()

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = _sanitize_run_id(document_id or file_path.stem or "qianfan_ocr")
        return (file_path.parent / ".qianfan_ocr" / run_id).absolute()

    def _post_multipart(self, *, file_path: Path) -> requests.Response:
        file_bytes = file_path.read_bytes()
        suffix = (file_path.suffix).lower()
        content_type = "application/pdf" if suffix == ".pdf" else "application/octet-stream"
        files = {"file": (file_path.name, file_bytes, content_type)}
        data = {
            "output_format": "markdown",
            "layout_as_thought": str(self._layout_as_thought).lower(),
        }
        return self._session.post(self._api_url, files=files, data=data, timeout=self._timeout_sec)

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

        logger.info("[qianfan_ocr] parsing %s", file_path.name)
        resp = self._post_multipart(file_path=file_path)
        if resp.status_code != 200:
            raise RuntimeError(f"Qianfan-OCR API error {resp.status_code}: {(resp.text)[:500]}")

        markdown_text = ""
        ctype = str(resp.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            try:
                data = resp.json()
            except Exception:
                data = json.loads((resp.text).strip() or "{}")
            markdown_text = _extract_markdown_from_json(data)
        else:
            markdown_text = resp.text

        try:
            artifact_root.mkdir(parents=True, exist_ok=True)
            (artifact_root / "result.md").write_text(markdown_text, encoding="utf-8")
        except Exception as exc:
            # Best-effort only; do not block parsing.
            logger.debug("Failed to write Qianfan OCR parse artifact; continuing: %s", exc)

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": "pdf",
            "parser_backend": "qianfan_ocr",
            "artifact_dir": str(artifact_root),
            "qianfan_ocr_layout_as_thought": self._layout_as_thought,
        }
        if dataset_id:
            metadata["dataset_id"] = str(dataset_id)

        return [Document(page_content=markdown_text, metadata=metadata)]
