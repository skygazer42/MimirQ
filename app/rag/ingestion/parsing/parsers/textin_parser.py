"""
TextIn xParse parser (external API).

Config via env/.env:
- TEXTIN_ENABLED=true
- TEXTIN_API_URL=https://api.textin.com/ai/service/v1/pdf_to_markdown
- TEXTIN_APP_ID=<app-id>
- TEXTIN_SECRET_CODE=<secret-code>
"""

import json
import logging
from pathlib import Path
from typing import Any

import requests
from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.ingestion.parsing.utils.artifact_normalizer import sanitize_artifact_run_id

logger = logging.getLogger("parsing.textin")


def _collect_text_records(records: Any) -> list[str]:
    if not isinstance(records, list):
        return []
    texts: list[str] = []
    previous_continues = False
    for record in records:
        if not isinstance(record, dict):
            previous_continues = False
            continue
        text = record.get("text")
        if not isinstance(text, str) or not text.strip():
            previous_continues = False
            continue
        if previous_continues and texts:
            texts[-1] += text
        else:
            texts.append(text)
        metadata = record.get("metadata")
        previous_continues = isinstance(metadata, dict) and metadata.get("is_continue") is True
    return texts


def _extract_markdown_from_payload(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    result = data.get("result")
    if not isinstance(result, dict):
        return ""
    for key in ("markdown", "text", "content"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value
    for key in ("elements", "detail"):
        records = result.get(key)
        if records is not None:
            return "\n\n".join(_collect_text_records(records))
    pages = result.get("pages")
    texts: list[str] = []
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            records = page.get("content")
            if records is None:
                records = page.get("structured")
            texts.extend(_collect_text_records(records))
    return "\n\n".join(texts)


def _extract_error_message(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    for key in ("message", "msg", "detail", "error"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class TextInParser:
    """
    Call the TextIn xParse quickstart endpoint and return Markdown output.

    The endpoint accepts binary request bodies plus auth headers and returns
    JSON with `result.markdown` for markdown-oriented parse modes.
    """

    def __init__(self) -> None:
        self._enabled = settings.TEXTIN_ENABLED
        self._api_url = settings.TEXTIN_API_URL.strip()
        self._app_id = settings.TEXTIN_APP_ID.strip()
        self._secret_code = settings.TEXTIN_SECRET_CODE.strip()
        self._timeout_sec = settings.TEXTIN_TIMEOUT_SEC
        self._parse_mode = settings.TEXTIN_PARSE_MODE.strip().lower() or "auto"
        self._table_flavor = settings.TEXTIN_TABLE_FLAVOR.strip().lower() or "html"
        self._apply_document_tree = settings.TEXTIN_APPLY_DOCUMENT_TREE
        self._markdown_details = settings.TEXTIN_MARKDOWN_DETAILS
        self._get_image = settings.TEXTIN_GET_IMAGE.strip().lower() or "none"
        self._dpi = max(0, settings.TEXTIN_DPI)
        self._page_count = max(0, settings.TEXTIN_PAGE_COUNT)

        if not self._enabled:
            raise RuntimeError("TextIn is disabled (TEXTIN_ENABLED=false).")
        if not self._api_url:
            raise RuntimeError("TextIn requires TEXTIN_API_URL.")
        if not self._app_id:
            raise RuntimeError("TextIn requires TEXTIN_APP_ID.")
        if not self._secret_code:
            raise RuntimeError("TextIn requires TEXTIN_SECRET_CODE.")

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = sanitize_artifact_run_id(document_id or file_path.stem or "textin", fallback="textin")
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
        headers = {
            "accept": "application/json,text/plain,*/*",
            "content-type": "application/octet-stream",
            "x-ti-app-id": self._app_id,
            "x-ti-secret-code": self._secret_code,
        }
        with requests.Session() as session, file_path.open("rb") as file_handle:
            return session.post(
                self._api_url,
                params=self._request_params(),
                data=file_handle,
                headers=headers,
                timeout=self._timeout_sec,
            )

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

        with self._post_binary(file_path=file_path) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"TextIn API error {resp.status_code}: {resp.text[:500]}")
            data = resp.json()

        code = data.get("code") if isinstance(data, dict) else None
        if isinstance(code, bool) or code not in {None, 0, 200, "0", "200"}:
            message = _extract_error_message(data)
            raise RuntimeError(f"TextIn parse failed (code={code}): {message[:500]}")

        markdown_text = _extract_markdown_from_payload(data)
        if not markdown_text.strip():
            raise RuntimeError("TextIn API returned no Markdown or text records")

        try:
            artifact_root.mkdir(parents=True, exist_ok=True)
            (artifact_root / "result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            (artifact_root / "result.md").write_text(markdown_text, encoding="utf-8")
        except OSError as exc:
            logger.debug("Failed to write TextIn parse artifact; continuing: %s", exc)

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
