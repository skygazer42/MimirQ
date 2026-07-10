"""
GLM-OCR parser (external service).

GLM-OCR is an optional heavyweight OCR/layout pipeline. To avoid bloating the
main backend image, we integrate it as an external HTTP service.

Expected service behaviors (best-effort):
- Accept multipart/form-data with field name "file" (PDF)
- Return:
  - ZIP: Markdown + images (arbitrary folder layout)
  - JSON: {markdown/text/content/result: "..."}
  - text/*: markdown directly
"""


import re
import zipfile
from pathlib import Path
from typing import Any

import requests
from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.utils.artifact_normalizer import normalize_extracted_artifacts
from app.parsing.utils.zip_processor import ZipImageProcessor
from app.rag.core.logging import get_logger

logger = get_logger("parsing.glm_ocr")


def _sanitize_run_id(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)[:120] or "glmocr"
    return text


class GlmOCRParser:
    STANDARD_MARKDOWN_NAME = "result.md"

    def __init__(self) -> None:
        self._enabled = bool(getattr(settings, "GLM_OCR_ENABLED", False))
        self._api_url = (getattr(settings, "GLM_OCR_API_URL", "") or "").strip()
        self._timeout_sec = float(getattr(settings, "GLM_OCR_TIMEOUT_SEC", 600) or 600)
        self._pipeline_version = (getattr(settings, "GLM_OCR_PIPELINE_VERSION", "") or "").strip()

        if not self._enabled:
            raise RuntimeError("GLM-OCR is disabled (GLM_OCR_ENABLED=false).")
        if not self._api_url:
            raise RuntimeError("GLM-OCR requires GLM_OCR_API_URL.")

        self._session = requests.Session()

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = _sanitize_run_id(document_id or file_path.stem or "glmocr")
        return (file_path.parent / ".glmocr" / run_id).absolute()

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
            for key in ("markdown", "md", "content", "text", "result"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val
        return ""

    def _post_multipart(self, *, file_path: Path) -> requests.Response:
        file_bytes = file_path.read_bytes()
        files = {"file": (file_path.name, file_bytes, "application/pdf")}
        data = {"output_format": "markdown"}
        return self._session.post(self._api_url, files=files, data=data, timeout=self._timeout_sec)

    def _parse_zip_payload(self, *, artifact_root: Path, zip_bytes: bytes) -> tuple[str, dict[str, Any]]:
        artifact_root.mkdir(parents=True, exist_ok=True)
        zip_path = artifact_root / "glm_ocr.zip"
        zip_path.write_bytes(zip_bytes)

        extract_root = artifact_root / "extract"
        extract_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zf:
            ZipImageProcessor._safe_extract(zf, extract_root)

        norm = normalize_extracted_artifacts(
            extract_root,
            output_markdown_name=self.STANDARD_MARKDOWN_NAME,
            output_image_dir="images",
        )
        md_file = norm.get("markdown_file")
        if not isinstance(md_file, Path) or not md_file.exists():
            raise RuntimeError("GLM-OCR ZIP payload contained no markdown output")

        markdown_text = md_file.read_text(encoding="utf-8", errors="ignore")
        meta = {
            "asset_base_dir": str(extract_root.resolve(strict=False)),
            "artifact_dir": str(artifact_root.resolve(strict=False)),
            "zip_images": int(norm.get("image_count") or 0),
        }
        return markdown_text, meta

    def parse(
        self,
        file_path: Path,
        *,
        dataset_id: str | None = None,  # kept for interface parity
        document_id: str | None = None,
        **_kwargs,
    ) -> list[Document]:
        _ = dataset_id
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        resp = self._post_multipart(file_path=file_path)
        if resp.status_code >= 400:
            raise RuntimeError(f"GLM-OCR HTTP {resp.status_code}: {str(resp.text or '')[:500]}")

        markdown_text = ""
        extra_meta: dict[str, Any] = {}
        if self._looks_like_zip(resp):
            artifact_root = self._build_artifact_root(file_path, document_id)
            markdown_text, extra_meta = self._parse_zip_payload(artifact_root=artifact_root, zip_bytes=resp.content or b"")
        else:
            ctype = str(resp.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                try:
                    data = resp.json()
                except Exception:
                    data = None
                markdown_text = self._extract_markdown_from_json(data)
            if not markdown_text:
                # Fallback: treat as text.
                markdown_text = str(resp.text or "")

        markdown_text = str(markdown_text or "")

        # If object storage is disabled, strip local image references to avoid dead links.
        if not settings.MINIO_ENABLED and markdown_text:
            markdown_text = re.sub(r"!\[[^\]]*\]\(\s*[^)\s]+?\s*\)\s*", "", markdown_text)
            markdown_text = re.sub(r"<img[^>]*?>", "", markdown_text, flags=re.IGNORECASE)

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": "pdf",
            "parser_backend": "glm_ocr",
        }
        if self._pipeline_version:
            metadata["glm_ocr_pipeline_version"] = self._pipeline_version
        metadata.update(extra_meta)

        return [Document(page_content=markdown_text, metadata=metadata)]

