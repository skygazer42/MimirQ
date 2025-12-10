"""
MarkItDown PDF/Document parser adapter.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from langchain_core.documents import Document

from app.core.config import settings


class MarkItDownParser:
    """Wraps Microsoft's MarkItDown converter so it fits our parser interface."""

    def __init__(self):
        try:
            from markitdown import MarkItDown  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "MarkItDown is not installed. Please run `pip install markitdown` "
                "or enable it via requirements.txt before setting MARKITDOWN_ENABLED=True."
            ) from exc

        converter_kwargs = {
            "enable_plugins": settings.MARKITDOWN_USE_PLUGINS,
        }

        if settings.MARKITDOWN_DOCINTEL_ENDPOINT:
            converter_kwargs["docintel_endpoint"] = settings.MARKITDOWN_DOCINTEL_ENDPOINT
            if settings.MARKITDOWN_DOCINTEL_KEY:
                try:
                    from azure.core.credentials import AzureKeyCredential  # type: ignore
                except ImportError as exc:  # pragma: no cover - optional dependency
                    raise RuntimeError(
                        "MARKITDOWN_DOCINTEL_KEY is set but azure-core is not installed. "
                        "Install markitdown[all] or azure-core to enable Document Intelligence."
                    ) from exc
                converter_kwargs["docintel_credential"] = AzureKeyCredential(
                    settings.MARKITDOWN_DOCINTEL_KEY
                )

        self._converter = MarkItDown(**converter_kwargs)

    def parse(self, file_path: Path) -> List[Document]:
        try:
            result = self._converter.convert(str(file_path))
        except Exception as exc:  # pragma: no cover - surfaced to caller
            raise RuntimeError(f"MarkItDown failed to parse {file_path}: {exc}") from exc

        markdown_text = getattr(result, "markdown", "") or getattr(result, "text_content", "") or ""
        metadata = {
            "source": file_path.name,
            "file_type": file_path.suffix.lstrip("."),
            "parser_backend": "markitdown",
        }

        title: Optional[str] = getattr(result, "title", None)
        if title:
            metadata["title"] = title

        return [Document(page_content=markdown_text, metadata=metadata)]
