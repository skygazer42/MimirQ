"""
Standalone image parser adapter.

Phase 1 goals:
- Allow ingesting images as first-class documents by emitting a minimal Markdown
  payload referencing the local image file.
- Rely on existing InlineAssetStage to upload and rewrite image refs when MinIO
  is enabled.

Notes:
- This does not perform OCR/captioning directly. Downstream image pipelines can
  enrich image chunks when enabled.
"""


from pathlib import Path
from typing import Any
from urllib.parse import quote

from langchain_core.documents import Document

from app.parsing.enrich.table_markdown import markdown_table_from_image_path


class ImageParser:
    SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    def parse(self, file_path: Path, **kwargs: Any) -> list[Document]:
        _ = kwargs
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"ImageParser supports only {sorted(self.SUPPORTED_EXTENSIONS)}, got: {ext}")

        table_markdown = markdown_table_from_image_path(file_path)
        if table_markdown:
            metadata = {
                "source": file_path.name,
                "file_type": ext.lstrip("."),
                "parser_backend": "image",
                "asset_base_dir": str(file_path.parent.resolve(strict=False)),
                "doc_type_kwd": "table",
                "content_type": "table",
            }
            return [Document(page_content=table_markdown, metadata=metadata)]

        # Percent-encode to keep inline-asset regexes simple (no whitespace in refs).
        ref = quote(file_path.name, safe="._-()[]{}@!$&+,;=~")
        markdown = f"![]({ref})\n"
        metadata = {
            "source": file_path.name,
            "file_type": ext.lstrip("."),
            "parser_backend": "image",
            # InlineAssetStage resolves relative refs under this directory.
            "asset_base_dir": str(file_path.parent.resolve(strict=False)),
        }
        return [Document(page_content=markdown, metadata=metadata)]
