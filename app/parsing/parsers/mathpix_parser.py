from __future__ import annotations

from pathlib import Path
from typing import Any

import requests
from langchain_core.documents import Document

from app.core.config import settings


def _call_mathpix_backend(*, file_path: Path, app_id: str, app_key: str) -> str:
    with file_path.open("rb") as fh:
        resp = requests.post(
            "https://api.mathpix.com/v3/pdf",
            headers={
                "app_id": str(app_id or "").strip(),
                "app_key": str(app_key or "").strip(),
            },
            files={"file": (file_path.name, fh, "application/pdf")},
            timeout=30,
        )
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Mathpix parse failed: {exc}") from exc
    text = str((data or {}).get("text") or "").strip()
    if not text:
        raise RuntimeError("Mathpix parse failed: empty response")
    return text


class MathpixParser:
    SUPPORTED_EXTENSIONS = {".pdf"}

    def parse(self, file_path: Path, **kwargs: Any) -> list[Document]:
        _ = kwargs
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if file_path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"MathpixParser supports only {sorted(self.SUPPORTED_EXTENSIONS)}, got: {file_path.suffix.lower()}")

        app_id = str(getattr(settings, "MATHPIX_APP_ID", "") or "").strip()
        app_key = str(getattr(settings, "MATHPIX_APP_KEY", "") or "").strip()
        if not app_id or not app_key:
            raise RuntimeError("Mathpix is not configured")

        markdown = _call_mathpix_backend(file_path=file_path, app_id=app_id, app_key=app_key)
        return [
            Document(
                page_content=markdown,
                metadata={
                    "source": file_path.name,
                    "file_type": "pdf",
                    "parser_backend": "mathpix",
                },
            )
        ]
