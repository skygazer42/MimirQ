"""
MarkItDown PDF/Document parser adapter.
"""

import logging
import os
from contextlib import ExitStack
from pathlib import Path

import requests
from langchain_core.documents import Document
from markitdown import MarkItDown

from app.infrastructure.config import settings
from app.infrastructure.runtime.dependencies import require_dependency

logger = logging.getLogger("parsing.markitdown")


class MarkItDownParser:
    """Wraps Microsoft's MarkItDown converter so it fits our parser interface."""

    def __init__(self):
        self._use_plugins = settings.MARKITDOWN_USE_PLUGINS
        self._docintel_endpoint = settings.MARKITDOWN_DOCINTEL_ENDPOINT
        self._docintel_key = settings.MARKITDOWN_DOCINTEL_KEY

    def _convert(self, file_path: Path) -> tuple[str, str | None]:
        resources = ExitStack()
        pending_error: BaseException | None = None
        try:
            session = resources.enter_context(requests.Session())
            # Preserve the pinned SDK's default header when injecting its transport.
            session.headers.update({"Accept": "text/markdown, text/html;q=0.9, text/plain;q=0.8, */*;q=0.1"})
            converter = MarkItDown(enable_plugins=False, requests_session=session)
            plugin_kwargs = {}
            if self._docintel_endpoint:
                plugin_kwargs["docintel_endpoint"] = self._docintel_endpoint
                key = self._docintel_key or os.environ.get("AZURE_API_KEY")
                if key is None:
                    identity = require_dependency(
                        "azure.identity", feature="markitdown_docintel", pip_name="azure-identity"
                    )
                    credential = identity.DefaultAzureCredential()
                    resources.callback(credential.close)
                else:
                    credentials = require_dependency(
                        "azure.core.credentials", feature="markitdown_docintel", pip_name="azure-core"
                    )
                    credential = credentials.AzureKeyCredential(key)
                if self._docintel_key:
                    plugin_kwargs["docintel_credential"] = credential
                converters = require_dependency(
                    "markitdown.converters", feature="markitdown_docintel", pip_name="markitdown[az-doc-intel]"
                )
                docintel = converters.DocumentIntelligenceConverter(
                    endpoint=self._docintel_endpoint, credential=credential
                )
                resources.callback(docintel.doc_intel_client.close)
                # SDK 0.1.5 registers DocIntel after built-ins, then plugins.
                converter.register_converter(docintel)
            if self._use_plugins:
                converter.enable_plugins(**plugin_kwargs)
            result = converter.convert(file_path)
            return result.markdown, result.title
        except BaseException as exc:
            pending_error = exc
            raise
        finally:
            try:
                resources.close()
            except BaseException as close_error:
                if pending_error is None:
                    raise
                pending_error.add_note(f"MarkItDown resource cleanup failed: {type(close_error).__name__}")
                logger.warning("MarkItDown cleanup failed while propagating an error", exc_info=True)

    def parse(self, file_path: Path) -> list[Document]:
        file_path = Path(file_path)
        try:
            markdown_text, title = self._convert(file_path)
        except Exception as exc:  # pragma: no cover - surfaced to caller
            raise RuntimeError(f"MarkItDown failed to parse {file_path}: {exc}") from exc

        if not markdown_text.strip():
            raise RuntimeError("MarkItDown returned no Markdown content")
        metadata = {
            "source": file_path.name,
            "file_type": file_path.suffix.lstrip("."),
            "parser_backend": "markitdown",
        }

        if title:
            metadata["title"] = title

        return [Document(page_content=markdown_text, metadata=metadata)]
