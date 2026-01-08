"""
Text decoding helpers for parsers.

We ingest user-uploaded files from many sources; in practice, plain text /
markdown files are often not UTF-8 (or may include BOM). This module provides a
small, dependency-light decoder that:
- Tries UTF-8 (with BOM handling) first
- Falls back to chardet detection
- Decodes with replacement to avoid hard failures
"""


from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: str
    confidence: float
    had_bom: bool


def read_text_file(path: Path, *, default_encoding: str = "utf-8") -> DecodedText:
    """
    Read and decode a text file with best-effort encoding detection.

    Notes:
    - Always returns a string (decoding errors are replaced).
    - `confidence` is 1.0 for successful UTF-8 decode, otherwise derived from chardet.
    """
    blob = Path(path).read_bytes()
    had_bom = blob.startswith(b"\xef\xbb\xbf")

    # 1) Fast path: UTF-8 (with BOM stripping).
    try:
        return DecodedText(
            text=blob.decode("utf-8-sig", errors="strict"),
            encoding="utf-8",
            confidence=1.0,
            had_bom=had_bom,
        )
    except UnicodeDecodeError:
        pass

    # 2) Best-effort detection with chardet (optional dependency in minimal/full).
    encoding = default_encoding
    confidence = 0.0
    try:
        import chardet  # type: ignore

        detected = chardet.detect(blob[:65536])
        encoding = (detected.get("encoding") or "").strip() or default_encoding
        confidence = float(detected.get("confidence") or 0.0)
        if encoding.lower() == "ascii":
            encoding = "utf-8"
    except Exception:
        encoding = default_encoding
        confidence = 0.0

    # 3) Decode using detected encoding, falling back to default.
    try:
        text = blob.decode(encoding, errors="replace")
    except Exception:
        encoding = default_encoding
        confidence = 0.0
        text = blob.decode(default_encoding, errors="replace")

    return DecodedText(text=text, encoding=str(encoding), confidence=float(confidence), had_bom=had_bom)

