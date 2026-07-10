"""
MarkItDown PDF/Document parser adapter.
"""

from pathlib import Path

from langchain_core.documents import Document
from markitdown import MarkItDown

from app.core.config import settings
from app.core.optional_deps import require_dependency


class MarkItDownParser:
    """Wraps Microsoft's MarkItDown converter so it fits our parser interface."""

    def __init__(self):
        converter_kwargs = {
            "enable_plugins": settings.MARKITDOWN_USE_PLUGINS,
        }

        if settings.MARKITDOWN_DOCINTEL_ENDPOINT:
            converter_kwargs["docintel_endpoint"] = settings.MARKITDOWN_DOCINTEL_ENDPOINT
            if settings.MARKITDOWN_DOCINTEL_KEY:
                credentials_mod = require_dependency(
                    "azure.core.credentials",
                    feature="markitdown_docintel",
                    pip_name="azure-core",
                )
                credential_cls = getattr(credentials_mod, "AzureKeyCredential", None)
                if credential_cls is None:
                    raise RuntimeError("azure.core.credentials.AzureKeyCredential missing (unsupported azure-core version)")
                converter_kwargs["docintel_credential"] = credential_cls(
                    settings.MARKITDOWN_DOCINTEL_KEY
                )

        self._converter = MarkItDown(**converter_kwargs)

    def parse(self, file_path: Path) -> list[Document]:
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

        title: str | None = getattr(result, "title", None)
        if title:
            metadata["title"] = title

        return [Document(page_content=markdown_text, metadata=metadata)]
