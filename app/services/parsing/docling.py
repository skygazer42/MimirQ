"""Thin HTTP adapter for an external Docling Serve deployment.

Docling and its model stack intentionally live outside the MimirQ API/worker
runtime.  This module preserves the legacy ``(sections, tables)`` parser
contract while calling Docling Serve's stable v1 REST API.
"""

import logging
import mimetypes
import re
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from io import BytesIO
from os import PathLike
from pathlib import Path
from typing import Any, BinaryIO, Literal
from urllib.parse import urlparse, urlunparse

import requests

from app.infrastructure.config import settings

_CONVERT_PATH_SUFFIXES = ("/v1/convert/file", "/v1/convert/source", "/v1")
_SUCCESS_STATUSES = {"success", "partial_success"}
_POSITION_TAG_RE = re.compile(r"@@[0-9-]+\t[0-9.]+\t[0-9.]+\t[0-9.]+\t[0-9.]+##")
logger = logging.getLogger(__name__)


def normalize_docling_base_url(value: str) -> str:
    """Accept either a service base URL or a stable-v1 conversion endpoint."""

    raw = value.strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
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


def validate_docling_max_pages(max_pages: int | None) -> None:
    if max_pages is not None and (isinstance(max_pages, bool) or not isinstance(max_pages, int) or max_pages <= 0):
        raise ValueError("Docling max_pages must be a positive integer or None")


def _close_resources(resources: ExitStack, pending_error: BaseException | None) -> None:
    try:
        resources.close()
    except BaseException as close_error:
        if pending_error is None:
            raise
        pending_error.add_note(f"Docling resource cleanup failed: {type(close_error).__name__}")
        logger.warning("Docling cleanup failed while propagating an error", exc_info=True)


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
        self.enabled = settings.DOCLING_ENABLED
        self.api_url = normalize_docling_base_url(api_url if api_url is not None else settings.DOCLING_API_URL)
        self.api_key = (api_key if api_key is not None else settings.DOCLING_API_KEY).strip()
        self.request_timeout_sec = float(
            settings.DOCLING_REQUEST_TIMEOUT_SEC if request_timeout_sec is None else request_timeout_sec
        )
        self.health_timeout_sec = float(
            settings.DOCLING_HEALTH_TIMEOUT_SEC if health_timeout_sec is None else health_timeout_sec
        )
        self.trust_env = bool(settings.DOCLING_HTTP_TRUST_ENV if trust_env is None else trust_env)
        self.ocr_enabled = bool(settings.DOCLING_OCR_ENABLED if ocr_enabled is None else ocr_enabled)
        self._session = session
        self.unavailable_reason = ""
        # Kept for compatibility with callers that inspect local parser fields.
        # Remote service responses do not expose process-local PIL images.
        self.page_images: list[Any] = []
        self.page_from = 0

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    @contextmanager
    def _request(self, method: Literal["get", "post"], url: str, **kwargs: Any) -> Iterator[requests.Response]:
        resources = ExitStack()
        try:
            session = self._session
            if session is None:
                session = requests.Session()
                resources.callback(session.close)
                session.trust_env = self.trust_env
            response = getattr(session, method)(url, **kwargs)
            resources.callback(response.close)
            yield response
        except BaseException as exc:
            _close_resources(resources, exc)
            raise
        else:
            _close_resources(resources, None)

    def check_installation(self) -> bool:
        """Return whether the configured external service is reachable."""

        if not self.enabled:
            self.unavailable_reason = "DOCLING_ENABLED=false"
            return False
        if not self.api_url:
            self.unavailable_reason = "DOCLING_API_URL is not configured"
            return False
        try:
            with self._request(
                "get",
                docling_health_url(self.api_url),
                headers=self._headers(),
                timeout=self.health_timeout_sec,
            ) as response:
                response.raise_for_status()
        except requests.RequestException as exc:
            self.unavailable_reason = f"Docling service health check failed: {str(exc)[:240]}"
            return False
        self.unavailable_reason = ""
        return True

    @staticmethod
    @contextmanager
    def _source_payload(
        filepath: str | PathLike[str], binary: BytesIO | bytes | None
    ) -> Iterator[tuple[Path, BinaryIO | bytes]]:
        source_path = Path(filepath)
        resources = ExitStack()
        try:
            if binary is None:
                content = source_path.open("rb")
                resources.callback(content.close)
                yield source_path, content
            elif isinstance(binary, (bytes, bytearray)):
                yield source_path, bytes(binary)
            else:
                position = binary.tell()
                binary.seek(0)
                resources.callback(binary.seek, position)
                yield source_path, binary
        except BaseException as exc:
            _close_resources(resources, exc)
            raise
        else:
            _close_resources(resources, None)

    @staticmethod
    def _input_format(source_path: Path) -> str:
        extension = source_path.suffix.lower().lstrip(".")
        aliases = {"htm": "html", "markdown": "md", "adoc": "asciidoc"}
        return aliases.get(extension, extension or "pdf")

    def _request_options(self, source_path: Path, *, max_pages: int | None = None) -> list[tuple[str, str]]:
        options = [
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
        if max_pages is not None:
            # Serve v1.28.0 FormDepends receives PageRange as repeated tuple fields.
            options.extend([("page_range", "1"), ("page_range", str(max_pages))])
        return options

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
        *,
        max_pages: int | None = None,
        **_kwargs: Any,
    ) -> tuple[list[tuple[str, str]], list[Any]]:
        """Convert one document and return the legacy sections/tables shape."""

        if not self.enabled:
            raise RuntimeError("Docling service is disabled (DOCLING_ENABLED=false).")
        if not self.api_url:
            raise RuntimeError("Docling service requires DOCLING_API_URL.")

        validate_docling_max_pages(max_pages)
        with self._source_payload(filepath, binary) as (source_path, content):
            if callback:
                callback(0.1, f"[Docling service] Converting: {source_path.name}")
            mime_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
            try:
                with self._request(
                    "post",
                    docling_convert_url(self.api_url),
                    headers=self._headers(),
                    files={"files": (source_path.name or "document.pdf", content, mime_type)},
                    data=self._request_options(source_path, max_pages=max_pages),
                    timeout=self.request_timeout_sec,
                ) as response:
                    response.raise_for_status()
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise RuntimeError("Docling service returned a non-JSON response.") from exc
            except requests.RequestException as exc:
                raise RuntimeError(f"Docling service request failed: {str(exc)[:500]}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Docling service returned an invalid response payload.")

        status = payload.get("status")
        if status is not None:
            status = str(status).strip().lower()
        if status not in _SUCCESS_STATUSES:
            raise RuntimeError(f"Docling conversion failed: {self._error_summary(payload)}")
        markdown = self._response_markdown(payload)
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
        return _POSITION_TAG_RE.sub("", text)
