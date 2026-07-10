
from pathlib import Path
from typing import Any
from urllib.parse import quote

from langchain_core.documents import Document


class VideoParser:
    SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

    def parse(self, file_path: Path, **kwargs: Any) -> list[Document]:
        _ = kwargs
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"VideoParser supports only {sorted(self.SUPPORTED_EXTENSIONS)}, got: {ext}")

        ref = quote(file_path.name, safe="._-()[]{}@!$&+,;=~")
        markdown = f"[video]({ref})\n"
        metadata = {
            "source": file_path.name,
            "file_type": ext.lstrip("."),
            "parser_backend": "video",
            "asset_base_dir": str(file_path.parent.resolve(strict=False)),
            "doc_type_kwd": "video",
            "content_type": "video",
        }
        return [Document(page_content=markdown, metadata=metadata)]
