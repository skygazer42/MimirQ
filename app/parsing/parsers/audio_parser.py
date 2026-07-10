
from pathlib import Path
from typing import Any
from urllib.parse import quote

from langchain_core.documents import Document


class AudioParser:
    SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

    def parse(self, file_path: Path, **kwargs: Any) -> list[Document]:
        _ = kwargs
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = file_path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"AudioParser supports only {sorted(self.SUPPORTED_EXTENSIONS)}, got: {ext}")

        ref = quote(file_path.name, safe="._-()[]{}@!$&+,;=~")
        markdown = f"[audio]({ref})\n"
        metadata = {
            "source": file_path.name,
            "file_type": ext.lstrip("."),
            "parser_backend": "audio",
            "asset_base_dir": str(file_path.parent.resolve(strict=False)),
            "doc_type_kwd": "audio",
            "content_type": "audio",
        }
        return [Document(page_content=markdown, metadata=metadata)]
