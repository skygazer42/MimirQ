"""Thin HTTP adapter for an external Docling Serve deployment.

Docling and its model stack intentionally live outside the MimirQ API/worker
runtime.  This module preserves the legacy ``(sections, tables)`` parser
contract while calling Docling Serve's stable v1 REST API.
"""

import mimetypes
import re
from collections.abc import Callable
from io import BytesIO
from os import PathLike
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests

from app.core.config import settings

_CONVERT_PATH_SUFFIXES = ("/v1/convert/file", "/v1/convert/source", "/v1")
_SUCCESS_STATUSES = {"success", "partial_success"}
_POSITION_TAG_RE = re.compile(r"@@[0-9-]+\t[0-9.]+\t[0-9.]+\t[0-9.]+\t[0-9.]+##")


def normalize_docling_base_url(value: str) -> str:
    """Accept either a service base URL or a stable-v1 conversion endpoint."""

    raw = (value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = (parsed.path or "").rstrip("/")
    for suffix in _CONVERT_PATH_SUFFIXES:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunparse(parsed._replace(path=path, params="", query="", fragment="")).rstrip("/")


def docling_convert_url(value: str) -> str:
    base_url = normalize_docling_base_url(value)
    return f"{base_url}/v1/convert/file" if base_url else ""


def docling_health_url(value: str) -> str:
    base_url = normalize_docling_base_url(value)
    return f"{base_url}/health" if base_url else ""


class DoclingServiceParser:
    """Compatibility parser backed exclusively by an external Docling service."""

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        request_timeout_sec: float | None = None,
        health_timeout_sec: float | None = None,
        trust_env: bool | None = None,
        ocr_enabled: bool | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.enabled = bool(getattr(settings, "DOCLING_ENABLED", False))
        self.api_url = normalize_docling_base_url(
            api_url if api_url is not None else str(getattr(settings, "DOCLING_API_URL", "") or "")
        )
        self.api_key = (
            api_key if api_key is not None else str(getattr(settings, "DOCLING_API_KEY", "") or "")
        ).strip()
        self.request_timeout_sec = float(
            request_timeout_sec
            if request_timeout_sec is not None
            else (getattr(settings, "DOCLING_REQUEST_TIMEOUT_SEC", 600) or 600)
        )
        self.health_timeout_sec = float(
            health_timeout_sec
            if health_timeout_sec is not None
            else (getattr(settings, "DOCLING_HEALTH_TIMEOUT_SEC", 5) or 5)
        )
        self.trust_env = bool(
            getattr(settings, "DOCLING_HTTP_TRUST_ENV", False) if trust_env is None else trust_env
        )
        self.ocr_enabled = bool(
            getattr(settings, "DOCLING_OCR_ENABLED", True) if ocr_enabled is None else ocr_enabled
        )
        self._session = session or requests.Session()
        if session is None:
            self._session.trust_env = self.trust_env
        self.unavailable_reason = ""
        # Kept for compatibility with callers that inspect local parser fields.
        # Remote service responses do not expose process-local PIL images.
        self.page_images: list[Any] = []
        self.page_from = 0

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    def check_installation(self) -> bool:
        """Return whether the configured external service is reachable."""

        if not self.enabled:
            self.unavailable_reason = "DOCLING_ENABLED=false"
            return False
        if not self.api_url:
            self.unavailable_reason = "DOCLING_API_URL is not configured"
            return False
        try:
            response = self._session.get(
                docling_health_url(self.api_url),
                headers=self._headers(),
                timeout=self.health_timeout_sec,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            self.unavailable_reason = f"Docling service health check failed: {str(exc)[:240]}"
            return False
        self.unavailable_reason = ""
        return True

    @staticmethod
    def _source_bytes(filepath: str | PathLike[str], binary: BytesIO | bytes | None) -> tuple[Path, bytes]:
        source_path = Path(filepath)
        if binary is None:
            if not source_path.exists():
                raise FileNotFoundError(f"Document not found: {source_path}")
            return source_path, source_path.read_bytes()
        if isinstance(binary, (bytes, bytearray)):
            return source_path, bytes(binary)
        return source_path, bytes(binary.getbuffer())

    @staticmethod
    def _input_format(source_path: Path) -> str:
        extension = source_path.suffix.lower().lstrip(".")
        aliases = {"htm": "html", "markdown": "md", "adoc": "asciidoc"}
        return aliases.get(extension, extension or "pdf")

    def _request_options(self, source_path: Path) -> list[tuple[str, str]]:
        return [
            ("from_formats", self._input_format(source_path)),
            ("to_formats", "md"),
            ("do_ocr", str(self.ocr_enabled).lower()),
            ("do_table_structure", "true"),
            ("table_mode", "accurate"),
            ("image_export_mode", "placeholder"),
            ("include_images", "false"),
            ("generate_page_images", "false"),
            ("generate_picture_images", "false"),
            ("abort_on_error", "false"),
            ("document_timeout", str(max(1, int(self.request_timeout_sec)))),
        ]

    @staticmethod
    def _response_markdown(payload: dict[str, Any]) -> str:
        document = payload.get("document")
        if not isinstance(document, dict):
            return ""
        for key in ("md_content", "text_content", "html_content"):
            value = document.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @staticmethod
    def _error_summary(payload: dict[str, Any]) -> str:
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            return str(errors[0])[:500]
        if errors:
            return str(errors)[:500]
        return str(payload.get("status") or "unknown error")[:500]

    def parse_pdf(
        self,
        filepath: str | PathLike[str],
        binary: BytesIO | bytes | None = None,
        callback: Callable[[float, str], None] | None = None,
        **_kwargs: Any,
    ) -> tuple[list[tuple[str, str]], list[Any]]:
        """Convert one document and return the legacy sections/tables shape."""

        if not self.enabled:
            raise RuntimeError("Docling service is disabled (DOCLING_ENABLED=false).")
        if not self.api_url:
            raise RuntimeError("Docling service requires DOCLING_API_URL.")

        source_path, content = self._source_bytes(filepath, binary)
        if callback:
            callback(0.1, f"[Docling service] Converting: {source_path.name}")
        mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        try:
            response = self._session.post(
                docling_convert_url(self.api_url),
                headers=self._headers(),
                files={"files": (source_path.name or "document.pdf", content, mime_type)},
                data=self._request_options(source_path),
                timeout=self.request_timeout_sec,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Docling service request failed: {str(exc)[:500]}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("Docling service returned a non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Docling service returned an invalid response payload.")

        status = str(payload.get("status") or "").strip().lower()
        markdown = self._response_markdown(payload)
        if status not in _SUCCESS_STATUSES:
            raise RuntimeError(f"Docling conversion failed: {self._error_summary(payload)}")
        if not markdown:
            raise RuntimeError("Docling service returned an empty document.")

        if callback:
            callback(1.0, "[Docling service] Conversion complete")
        return [(markdown, "")], []

    @staticmethod
    def crop(_text: str, need_position: bool = False):
        """Remote Markdown has no process-local page images to crop."""

        _ = need_position
        raise NotImplementedError

    @staticmethod
    def remove_tag(text: str) -> str:
        return _POSITION_TAG_RE.sub("", text or "")
