
from pathlib import Path
from typing import Any
from urllib.parse import quote

from langchain_core.documents import Document


class ColPaliParser:
    SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    def parse(self, file_path: Path, **kwargs: Any) -> list[Document]:
        _ = kwargs
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"ColPaliParser supports only {sorted(self.SUPPORTED_EXTENSIONS)}, got: {ext}")

        ref = quote(file_path.name, safe="._-()[]{}@!$&+,;=~")
        if ext == ".pdf":
            markdown = f"[visual-document]({ref})\n"
        else:
            markdown = f"![visual-document]({ref})\n"
        metadata = {
            "source": file_path.name,
            "file_type": ext.lstrip("."),
            "parser_backend": "colpali",
            "asset_base_dir": str(file_path.parent.resolve(strict=False)),
            "doc_type_kwd": "image",
            "content_type": "visual_document",
            "visual_parser": "colpali",
        }
        return [Document(page_content=markdown, metadata=metadata)]
