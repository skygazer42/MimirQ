"""
JSON parser (fallback / lightweight).

Provides a robust JSON/JSONL parser that returns pretty-printed JSON text and
basic structural metadata. This is useful as a fallback when MarkItDown is not
available or fails.
"""


import json
import logging
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.parsing.utils.text import read_text_file


def _try_parse_jsonl(raw: str) -> list[Any] | None:
    items: list[Any] = []
    parsed = 0
    total = 0
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        total += 1
        try:
            items.append(json.loads(stripped))
            parsed += 1
        except Exception:
            # Keep scanning; we decide based on ratio.
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
    if total >= 2 and parsed >= max(2, int(total * 0.7)):
        return items
    return None


class JsonParser:
    """Parse JSON / JSONL into a chunk-friendly text representation."""

    def parse(self, file_path: Path) -> list[Document]:
        decoded = read_text_file(file_path)
        raw = decoded.text or ""

        data: Any = None
        json_valid = False
        json_mode = "json"

        stripped = raw.strip()
        if stripped:
            try:
                data = json.loads(stripped)
                json_valid = True
            except Exception:
                # Try JSONL as a fallback.
                jsonl = _try_parse_jsonl(stripped)
                if jsonl is not None:
                    data = jsonl
                    json_valid = True
                    json_mode = "jsonl"

        if json_valid:
            content = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            content = raw

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": "json",
            "json_valid": bool(json_valid),
            "json_mode": json_mode,
            "encoding": decoded.encoding,
            "encoding_confidence": decoded.confidence,
            "encoding_had_bom": decoded.had_bom,
        }

        if json_valid:
            if isinstance(data, list):
                metadata["json_top_level"] = "array"
                metadata["json_items"] = len(data)
            elif isinstance(data, dict):
                metadata["json_top_level"] = "object"
                metadata["json_keys"] = list(data.keys())[:200]
            else:
                metadata["json_top_level"] = type(data).__name__

        return [Document(page_content=content, metadata=metadata)]

