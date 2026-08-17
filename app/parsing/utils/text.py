"""
Text decoding helpers for parsers.

We ingest user-uploaded files from many sources; in practice, plain text /
markdown files are often not UTF-8 (or may include BOM). This module provides a
small decoder that:
- Handles BOM (UTF-8/UTF-16/UTF-32) when present
- Tries UTF-8 first
- Uses chardet as a hint (when available)
- Falls back to common encodings (GB18030/GBK/BIG5/CP1252/Latin-1, etc.)
- Always returns a string (worst-case with replacement)
"""

from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.optional_deps import optional_import
from app.rag.core.logging import get_logger

logger = get_logger(__name__)
_TEXT_DECODE_FALLBACK_LOG_MESSAGE = "Ignoring non-critical text decode fallback failure: %s"


@dataclass(frozen=True)
class DecodedText:
    text: str
    encoding: str
    confidence: float
    had_bom: bool


_BOM_UTF8 = b"\xef\xbb\xbf"
_BOM_UTF16_LE = b"\xff\xfe"
_BOM_UTF16_BE = b"\xfe\xff"
_BOM_UTF32_LE = b"\xff\xfe\x00\x00"
_BOM_UTF32_BE = b"\x00\x00\xfe\xff"


@lru_cache(maxsize=1)
def _get_chardet():  # noqa: ANN202
    # Cache to avoid repeated warnings during large ingests when chardet isn't installed.
    return optional_import("chardet", feature="text_encoding_detection")


def _normalize_encoding(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    lowered = raw.lower().replace("_", "-")
    # Common aliases from chardet / user-land.
    if lowered in {"utf-8-sig", "utf8-sig"}:
        return "utf-8"
    if lowered in {"utf8"}:
        return "utf-8"
    if lowered in {"ascii"}:
        return "utf-8"
    if lowered in {"gb2312", "gbk"}:
        # Superset, more forgiving for legacy simplified Chinese.
        return "gb18030"
    if lowered in {"big5"}:
        return "big5"
    if lowered in {"windows-1252"}:
        return "cp1252"
    if lowered in {"iso-8859-1", "iso8859-1"}:
        return "latin1"
    return lowered


def _has_utf16_bom(blob: bytes) -> bool:
    return blob.startswith(_BOM_UTF16_LE) or blob.startswith(_BOM_UTF16_BE)


def _has_utf32_bom(blob: bytes) -> bool:
    return blob.startswith(_BOM_UTF32_LE) or blob.startswith(_BOM_UTF32_BE)


def _score_decoded_text(text: str) -> tuple[float, float, float]:
    """
    Heuristic scoring to pick the most likely "human readable" decode.

    Returns a tuple suitable for max() comparison:
    - (cjk_ratio_if_significant, printable_ratio, negative_nul_ratio)
    """
    if not text:
        return (0.0, 0.0, 0.0)

    total = len(text)
    nul = text.count("\x00")

    # Control characters (excluding common whitespace).
    control = 0
    cjk = 0
    for ch in text:
        code = ord(ch)
        if code == 0:
            continue
        if code < 32 and ch not in "\n\r\t\f":
            control += 1
            continue
        if code == 127:
            control += 1
            continue
        if (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF):
            cjk += 1

    printable = max(0, total - control - nul)
    printable_ratio = printable / max(1, total)
    nul_ratio = nul / max(1, total)

    cjk_ratio = cjk / max(1, total)
    # Only boost CJK if it is clearly present; avoids picking GB encodings for mostly Latin text.
    effective_cjk_ratio = cjk_ratio if (cjk >= 20 and cjk_ratio >= 0.10) else 0.0

    return (effective_cjk_ratio, printable_ratio, -nul_ratio)


def _iter_candidate_encodings(*, detected: str | None, default_encoding: str, blob: bytes) -> Iterable[str]:
    """
    Yield candidate encodings in priority order, de-duplicated.
    """
    seen: set[str] = set()

    def push(enc: str) -> None:
        norm = _normalize_encoding(enc)
        if not norm:
            return
        if norm in seen:
            return
        seen.add(norm)
        yield_list.append(norm)

    yield_list: list[str] = []

    # Detected encoding (from chardet) first, even if low confidence; we'll still score alternatives.
    if detected:
        push(detected)

    # If the file looks like UTF-16/32 without BOM (common on Windows exports), try these early.
    try:
        nul_ratio = blob.count(b"\x00") / max(1, len(blob))
    except Exception:
        nul_ratio = 0.0
    if nul_ratio >= 0.10:
        push("utf-16")
        push("utf-32")

    # Common fallbacks for "garbled Chinese" cases.
    push("gb18030")
    push("gbk")
    push("big5")

    # Western single-byte fallbacks.
    push("cp1252")
    push("latin1")

    # Last resort.
    push(default_encoding)

    return yield_list


def _decode_bom_text(blob: bytes) -> DecodedText | None:
    if _has_utf32_bom(blob):
        try:
            text = blob.decode("utf-32", errors="strict")
            return DecodedText(text=text.lstrip("\ufeff"), encoding="utf-32", confidence=1.0, had_bom=True)
        except UnicodeDecodeError as exc:
            logger.debug(_TEXT_DECODE_FALLBACK_LOG_MESSAGE, exc)

    if _has_utf16_bom(blob):
        try:
            text = blob.decode("utf-16", errors="strict")
            return DecodedText(text=text.lstrip("\ufeff"), encoding="utf-16", confidence=1.0, had_bom=True)
        except UnicodeDecodeError as exc:
            logger.debug(_TEXT_DECODE_FALLBACK_LOG_MESSAGE, exc)
    return None


def _detect_encoding(blob: bytes) -> tuple[str | None, float]:
    chardet = _get_chardet()
    if chardet is None:
        return None, 0.0
    try:
        detected = chardet.detect(blob[:65536])
        detected_encoding = (detected.get("encoding") or "").strip() or None
        detected_confidence = float(detected.get("confidence") or 0.0)
    except Exception:
        return None, 0.0
    return detected_encoding, detected_confidence


def _decode_best_candidate(
    blob: bytes,
    *,
    detected_encoding: str | None,
    default_encoding: str,
) -> tuple[str | None, str | None]:
    best_text: str | None = None
    best_encoding: str | None = None
    best_score: tuple[float, float, float] = (0.0, 0.0, 0.0)
    candidates = _iter_candidate_encodings(detected=detected_encoding, default_encoding=default_encoding, blob=blob)

    for enc in candidates:
        try:
            decoded = blob.decode(enc, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
        score = _score_decoded_text(decoded)
        if best_text is None or score > best_score:
            best_text = decoded
            best_encoding = enc
            best_score = score
    return best_text, best_encoding


def _replacement_decoded_text(
    blob: bytes,
    *,
    detected_encoding: str | None,
    detected_confidence: float,
    default_encoding: str,
    had_bom: bool,
) -> DecodedText:
    fallback = _normalize_encoding(detected_encoding or "") or default_encoding
    try:
        return DecodedText(
            text=blob.decode(fallback, errors="replace"),
            encoding=str(fallback),
            confidence=float(detected_confidence or 0.0),
            had_bom=had_bom,
        )
    except Exception:
        return DecodedText(
            text=blob.decode(default_encoding, errors="replace"),
            encoding=str(default_encoding),
            confidence=0.0,
            had_bom=had_bom,
        )


def read_text_file(path: Path, *, default_encoding: str = "utf-8") -> DecodedText:
    """
    Read and decode a text file with best-effort encoding detection.

    Notes:
    - Always returns a string (decoding errors are replaced).
    - `confidence` is 1.0 for successful UTF-8 decode, otherwise derived from chardet.
    """
    blob = Path(path).read_bytes()
    had_bom = blob.startswith(_BOM_UTF8) or _has_utf16_bom(blob) or _has_utf32_bom(blob)

    # 1) BOM-aware fast paths.
    bom_decoded = _decode_bom_text(blob)
    if bom_decoded is not None:
        return bom_decoded

    # 2) Fast path: UTF-8 (with BOM stripping).
    try:
        return DecodedText(
            text=blob.decode("utf-8-sig", errors="strict"),
            encoding="utf-8",
            confidence=1.0,
            had_bom=had_bom,
        )
    except UnicodeDecodeError as exc:
        logger.debug(_TEXT_DECODE_FALLBACK_LOG_MESSAGE, exc)

    # 3) Best-effort detection with chardet.
    detected_encoding, detected_confidence = _detect_encoding(blob)

    # 4) Try a small set of candidates and pick the best-scoring result.
    best_text, best_encoding = _decode_best_candidate(
        blob,
        detected_encoding=detected_encoding,
        default_encoding=default_encoding,
    )

    if best_text is None or best_encoding is None:
        return _replacement_decoded_text(
            blob,
            detected_encoding=detected_encoding,
            detected_confidence=detected_confidence,
            default_encoding=default_encoding,
            had_bom=had_bom,
        )

    confidence = (
        float(detected_confidence or 0.0) if _normalize_encoding(detected_encoding or "") == best_encoding else 0.0
    )
    return DecodedText(text=best_text, encoding=str(best_encoding), confidence=confidence, had_bom=had_bom)
