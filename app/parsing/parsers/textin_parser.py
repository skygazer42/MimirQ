"""
TextIn xParse parser (external API).

Config via env/.env:
- TEXTIN_ENABLED=true
- TEXTIN_API_URL=https://api.textin.com/ai/service/v1/pdf_to_markdown
- TEXTIN_APP_ID=<app-id>
- TEXTIN_SECRET_CODE=<secret-code>
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import requests
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("parsing.textin")


def _sanitize_run_id(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)[:120] or "textin"
    return text


def _collect_markdown_like_strings(node: Any) -> list[str]:
    results: list[str] = []
    if isinstance(node, str):
        if node.strip():
            results.append(node)
        return results
    if isinstance(node, list):
        for item in node:
            results.extend(_collect_markdown_like_strings(item))
        return results
    if isinstance(node, dict):
        for key in ("markdown", "content", "text", "value"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                results.append(value)
        for item in node.values():
            results.extend(_collect_markdown_like_strings(item))
    return results


class TextInParser:
    """
    Call the TextIn xParse quickstart endpoint and return Markdown output.

    The endpoint accepts binary request bodies plus auth headers and returns
    JSON with `result.markdown` for markdown-oriented parse modes.
    """

    def __init__(self) -> None:
        self._enabled = bool(getattr(settings, "TEXTIN_ENABLED", False))
        self._api_url = (getattr(settings, "TEXTIN_API_URL", "") or "").strip()
        self._app_id = (getattr(settings, "TEXTIN_APP_ID", "") or "").strip()
        self._secret_code = (getattr(settings, "TEXTIN_SECRET_CODE", "") or "").strip()
        self._timeout_sec = float(getattr(settings, "TEXTIN_TIMEOUT_SEC", 180) or 180)
        self._parse_mode = (getattr(settings, "TEXTIN_PARSE_MODE", "") or "auto").strip().lower() or "auto"
        self._table_flavor = (getattr(settings, "TEXTIN_TABLE_FLAVOR", "") or "html").strip().lower() or "html"
        self._apply_document_tree = bool(getattr(settings, "TEXTIN_APPLY_DOCUMENT_TREE", True))
        self._markdown_details = bool(getattr(settings, "TEXTIN_MARKDOWN_DETAILS", True))
        self._get_image = (getattr(settings, "TEXTIN_GET_IMAGE", "") or "none").strip().lower() or "none"
        self._dpi = max(0, int(getattr(settings, "TEXTIN_DPI", 144) or 0))
        self._page_count = max(0, int(getattr(settings, "TEXTIN_PAGE_COUNT", 0) or 0))

        if not self._enabled:
            raise RuntimeError("TextIn is disabled (TEXTIN_ENABLED=false).")
        if not self._api_url:
            raise RuntimeError("TextIn requires TEXTIN_API_URL.")
        if not self._app_id:
            raise RuntimeError("TextIn requires TEXTIN_APP_ID.")
        if not self._secret_code:
            raise RuntimeError("TextIn requires TEXTIN_SECRET_CODE.")

        self._session = requests.Session()

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = _sanitize_run_id(document_id or file_path.stem or "textin")
        return (file_path.parent / ".textin" / run_id).absolute()

    def _request_params(self) -> dict[str, str]:
        params: dict[str, str] = {
            "parse_mode": self._parse_mode,
            "table_flavor": self._table_flavor,
            "apply_document_tree": str(self._apply_document_tree).lower(),
            "markdown_details": str(self._markdown_details).lower(),
        }
        if self._get_image:
            params["get_image"] = self._get_image
        if self._dpi > 0:
            params["dpi"] = str(self._dpi)
        if self._page_count > 0:
            params["page_count"] = str(self._page_count)
        return params

    def _post_binary(self, *, file_path: Path) -> requests.Response:
        file_bytes = file_path.read_bytes()
        headers = {
            "accept": "application/json,text/plain,*/*",
            "content-type": "application/octet-stream",
            "x-ti-app-id": self._app_id,
            "x-ti-secret-code": self._secret_code,
        }
        return self._session.post(
            self._api_url,
            params=self._request_params(),
            data=file_bytes,
            headers=headers,
            timeout=self._timeout_sec,
        )

    @staticmethod
    def _extract_markdown_from_payload(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        result = data.get("result")
        if isinstance(result, dict):
            for key in ("markdown", "text", "content"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        strings = _collect_markdown_like_strings(result)
        deduped: list[str] = []
        seen: set[str] = set()
        for item in strings:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return "\n\n".join(s.strip() for s in deduped if s.strip()).strip()

    @staticmethod
    def _extract_error_message(data: Any) -> str:
        if not isinstance(data, dict):
            return ""
        for key in ("message", "msg", "detail", "error"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def parse(
        self,
        file_path: Path,
        *,
        dataset_id: str | None = None,
        document_id: str | None = None,
        tenant_id: str | None = None,  # noqa: ARG002
        pdf_quality: dict[str, Any] | None = None,  # noqa: ARG002
        **_kwargs,
    ) -> list[Document]:
        _ = (dataset_id, tenant_id, pdf_quality)
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        artifact_root = self._build_artifact_root(file_path, document_id)
        logger.info("[textin] parsing %s", file_path.name)

        resp = self._post_binary(file_path=file_path)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise RuntimeError(f"TextIn API error {resp.status_code}: {(resp.text or '')[:500]}")

        try:
            data = resp.json()
        except Exception:
            data = json.loads((resp.text or "").strip() or "{}")

        code = data.get("code") if isinstance(data, dict) else None
        if code not in {None, 0, 200, "0", "200"}:
            message = self._extract_error_message(data)
            raise RuntimeError(f"TextIn parse failed (code={code}): {message[:500]}")

        markdown_text = self._extract_markdown_from_payload(data)
        if not markdown_text and resp.text.strip():
            markdown_text = resp.text

        artifact_root.mkdir(parents=True, exist_ok=True)
        (artifact_root / "result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        (artifact_root / "result.md").write_text(markdown_text or "", encoding="utf-8")

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": file_path.suffix.lstrip("."),
            "parser_backend": "textin",
            "artifact_dir": str(artifact_root),
            "textin_parse_mode": self._parse_mode,
            "textin_table_flavor": self._table_flavor,
            "textin_markdown_details": self._markdown_details,
        }
        if dataset_id:
            metadata["dataset_id"] = str(dataset_id)

        return [Document(page_content=markdown_text, metadata=metadata)]
