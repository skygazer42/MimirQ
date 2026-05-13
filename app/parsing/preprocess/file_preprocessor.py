"""
File-level preprocessing (before parsing).

This module sits *before* the parsing subprocess backends. It is meant to:
- Repair common text encoding issues (garbled UTF-8 / Windows-1252 / BOM)
- Normalize newlines/whitespace to reduce parser noise
- Strip obvious HTML non-content (script/style/comments) before HTML->MD conversion

Security:
- No executable code; steps are whitelisted by id.
- Preprocessing is bounded by a maximum byte budget to avoid OOM/DoS.
"""

from __future__ import annotations

from app.rag.core.logging import get_logger
import hashlib
import os
import re
import time
import unicodedata
import uuid
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.optional_deps import optional_import

logger = get_logger(__name__)

TEXT_LIKE_EXTS = {
    ".txt",
    ".md",
    ".rst",
    ".adoc",
    ".csv",
    ".json",
    ".html",
    ".htm",
    ".xml",
    ".yaml",
    ".yml",
    ".toml",
    ".log",
    ".ini",
    ".cfg",
    ".conf",
    ".env",
    ".properties",
    # Common code/text formats (safe to preprocess as text).
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".php",
    ".rb",
    ".sh",
    ".sql",
}


@dataclass(frozen=True)
class PreprocessStepLog:
    id: str
    applied: bool
    changed: bool
    note: str = ""
    bytes_before: int = 0
    bytes_after: int = 0
    elapsed_ms: int = 0


@dataclass(frozen=True)
class FilePreprocessResult:
    input_path: str
    output_path: str
    changed: bool
    size_before: int
    size_after: int
    sha256_before: str
    sha256_after: str
    steps: list[PreprocessStepLog]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "changed": bool(self.changed),
            "size_before": int(self.size_before),
            "size_after": int(self.size_after),
            "sha256_before": self.sha256_before,
            "sha256_after": self.sha256_after,
            "steps": [
                {
                    "id": s.id,
                    "applied": bool(s.applied),
                    "changed": bool(s.changed),
                    "note": s.note,
                    "bytes_before": int(getattr(s, "bytes_before", 0) or 0),
                    "bytes_after": int(getattr(s, "bytes_after", 0) or 0),
                    "elapsed_ms": int(getattr(s, "elapsed_ms", 0) or 0),
                }
                for s in (self.steps or [])
            ],
            "warnings": list(self.warnings or []),
        }


def _sha256_file(path: Path, *, max_bytes: int = 50_000_000) -> str:
    h = hashlib.sha256()
    total = 0
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if max_bytes > 0 and total > max_bytes:
                # Hashing very large files can be expensive; cap to keep it bounded.
                break
            h.update(chunk)
    return h.hexdigest()


def _read_bytes_bounded(path: Path, *, max_bytes: int) -> tuple[bytes, bool]:
    """
    Read at most max_bytes (+1 for truncation detection) from disk.
    """
    cap = int(max_bytes or 0)
    if cap <= 0:
        data = path.read_bytes()
        return data, False
    with open(path, "rb") as f:
        data = f.read(cap + 1)
    if len(data) > cap:
        return data[:cap], True
    return data, False


@lru_cache(maxsize=1)
def _get_charset_normalizer():  # noqa: ANN202
    # Cache to avoid repeated warnings during large ingests when deps aren't installed.
    return optional_import(
        "charset_normalizer",
        feature="file_preprocess_encoding_detection",
        pip_name="charset-normalizer",
    )


@lru_cache(maxsize=1)
def _get_chardet():  # noqa: ANN202
    return optional_import("chardet", feature="file_preprocess_encoding_detection")


def _detect_encoding(raw: bytes) -> tuple[str, float]:
    """
    Best-effort encoding detection.

    Returns (encoding, confidence).
    """
    # Prefer charset_normalizer (more accurate on short samples; pure python).
    cn = _get_charset_normalizer()
    if cn is not None:
        from_bytes = getattr(cn, "from_bytes", None)
        if callable(from_bytes):
            try:
                best = from_bytes(raw).best()
                if best is not None and getattr(best, "encoding", None):
                    return str(best.encoding), float(getattr(best, "confidence", 0.0) or 0.0)
            except Exception as exc:
                logger.debug("Ignoring non-critical file preprocessor fallback failure: %s", exc)

    # Fallback to chardet (available in many envs).
    chardet = _get_chardet()
    if chardet is not None:
        detect = getattr(chardet, "detect", None)
        if callable(detect):
            try:
                res = detect(raw)
                enc = str((res or {}).get("encoding") or "").strip()
                conf = float((res or {}).get("confidence") or 0.0)
                if enc:
                    return enc, conf
            except Exception as exc:
                logger.debug("Ignoring non-critical file preprocessor fallback failure: %s", exc)

    return "utf-8", 0.0


_RE_SCRIPT_STYLE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_RE_HTML_COMMENT = re.compile(r"(?s)<!--.*?-->")
_RE_HTML_BOILERPLATE_TAGS = re.compile(r"(?is)<(nav|header|footer|aside|noscript)\b[^>]*>.*?</\1\s*>")


def preprocess_file(
    *,
    input_path: Path,
    steps: list[dict[str, Any]],
    output_path: Path | None = None,
    max_text_bytes: int = 10_000_000,
) -> FilePreprocessResult:
    """
    Apply whitelisted preprocessing steps to `input_path` and write to `output_path` if changed.

    If no changes are needed, output_path defaults to input_path (no extra file created).
    """
    input_path = Path(input_path)
    ext = input_path.suffix.lower()
    size_before = int(input_path.stat().st_size)
    sha_before = _sha256_file(input_path)

    warnings: list[str] = []
    logs: list[PreprocessStepLog] = []

    if not steps:
        return FilePreprocessResult(
            input_path=str(input_path),
            output_path=str(input_path),
            changed=False,
            size_before=size_before,
            size_after=size_before,
            sha256_before=sha_before,
            sha256_after=sha_before,
            steps=[],
            warnings=[],
        )

    is_text_like = ext in TEXT_LIKE_EXTS
    if not is_text_like:
        # For v1, only text-like preprocessing is supported.
        for s in steps:
            sid = str((s or {}).get("id") or "")
            logs.append(PreprocessStepLog(id=sid, applied=False, changed=False, note="skipped (non-text file)"))
        return FilePreprocessResult(
            input_path=str(input_path),
            output_path=str(input_path),
            changed=False,
            size_before=size_before,
            size_after=size_before,
            sha256_before=sha_before,
            sha256_after=sha_before,
            steps=logs,
            warnings=["non_text_file_skipped"],
        )

    raw, truncated = _read_bytes_bounded(input_path, max_bytes=max_text_bytes)
    if truncated:
        warnings.append(f"text_too_large_skipped(max={max_text_bytes})")
        for s in steps:
            sid = str((s or {}).get("id") or "")
            logs.append(PreprocessStepLog(id=sid, applied=False, changed=False, note="skipped (too large)"))
        return FilePreprocessResult(
            input_path=str(input_path),
            output_path=str(input_path),
            changed=False,
            size_before=size_before,
            size_after=size_before,
            sha256_before=sha_before,
            sha256_after=sha_before,
            steps=logs,
            warnings=warnings,
        )

    enc, conf = _detect_encoding(raw)
    try:
        text = raw.decode(enc, errors="replace")
    except Exception:
        text = raw.decode("utf-8", errors="replace")
        enc = "utf-8"
        conf = 0.0

    changed_any = False
    original_text = text
    # Bytes in/out for per-step audit (UTF-8 after decoding/normalization).
    try:
        current_bytes = len(text.encode("utf-8", errors="replace"))
    except Exception:
        current_bytes = int(len(text or ""))

    for step in steps:
        step_t0 = time.perf_counter()
        sid = str((step or {}).get("id") or "").strip().lower()
        applied = False
        changed = False
        note = ""
        bytes_before = int(current_bytes)

        if sid == "text.reencode_utf8":
            applied = True
            note = f"encoding={enc} conf={conf:.2f}"
            # Re-encoding is always applied; changed only if bytes differ after normalization.
            # (We decide final change after all steps.)
        elif sid == "text.strip_bom":
            applied = True
            if text.startswith("\ufeff"):
                text = text.lstrip("\ufeff")
                changed = True
        elif sid == "text.normalize_newlines":
            applied = True
            new = text.replace("\r\n", "\n").replace("\r", "\n")
            if new != text:
                text = new
                changed = True
        elif sid == "text.collapse_blank_lines":
            applied = True
            # Keep up to 2 consecutive newlines to avoid noisy whitespace inflation.
            new = re.sub(r"\n{3,}", "\n\n", text)
            if new != text:
                text = new
                changed = True
        elif sid == "text.trim_trailing_whitespace":
            applied = True
            # Trim spaces/tabs at EOL (keep newlines).
            new = re.sub(r"[\\t ]+\\n", "\n", text)
            if new != text:
                text = new
                changed = True
        elif sid == "text.remove_zero_width":
            applied = True
            # Remove common zero-width / soft-hyphen artifacts from scraped/PDF-origin text.
            new = re.sub(r"[\u200b\u200c\u200d\u2060\u00ad\ufeff]", "", text)
            if new != text:
                text = new
                changed = True
        elif sid == "text.remove_control_chars":
            applied = True
            # Drop ASCII control chars except TAB/LF/CR (CR can be normalized later).
            new = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
            if new != text:
                text = new
                changed = True
        elif sid == "text.normalize_unicode_nfc":
            applied = True
            new = unicodedata.normalize("NFC", text)
            if new != text:
                text = new
                changed = True
        elif sid == "text.normalize_unicode_nfkc":
            applied = True
            # Normalize full-width forms / compatibility characters (best-effort).
            new = unicodedata.normalize("NFKC", text)
            if new != text:
                text = new
                changed = True
        elif sid == "html.strip_scripts_styles":
            applied = True
            if ext in {".html", ".htm"}:
                new = _RE_SCRIPT_STYLE.sub("", text)
                if new != text:
                    text = new
                    changed = True
            else:
                note = "skipped (not html)"
        elif sid == "html.strip_comments":
            applied = True
            if ext in {".html", ".htm"}:
                new = _RE_HTML_COMMENT.sub("", text)
                if new != text:
                    text = new
                    changed = True
            else:
                note = "skipped (not html)"
        elif sid == "html.strip_boilerplate_tags":
            applied = True
            if ext in {".html", ".htm"}:
                new = _RE_HTML_BOILERPLATE_TAGS.sub("", text)
                if new != text:
                    text = new
                    changed = True
            else:
                note = "skipped (not html)"
        else:
            # Unknown ids should have been rejected earlier; still keep safe.
            note = "skipped (unknown)"

        if changed:
            changed_any = True
        try:
            if changed:
                current_bytes = len(text.encode("utf-8", errors="replace"))
            bytes_after = int(current_bytes)
        except Exception:
            bytes_after = int(bytes_before)
            current_bytes = int(bytes_before)
        elapsed_ms = int(round((time.perf_counter() - step_t0) * 1000))
        if elapsed_ms < 0:
            elapsed_ms = 0
        logs.append(
            PreprocessStepLog(
                id=sid,
                applied=applied,
                changed=changed,
                note=note,
                bytes_before=bytes_before,
                bytes_after=bytes_after,
                elapsed_ms=elapsed_ms,
            )
        )

    if text == original_text:
        changed_any = False

    if not changed_any:
        return FilePreprocessResult(
            input_path=str(input_path),
            output_path=str(input_path),
            changed=False,
            size_before=size_before,
            size_after=size_before,
            sha256_before=sha_before,
            sha256_after=sha_before,
            steps=logs,
            warnings=warnings,
        )

    # Default output path: sibling file in same directory to preserve relative asset resolution.
    if output_path is None:
        rand = uuid.uuid4().hex[:10]
        output_path = input_path.with_name(f"{input_path.stem}.pre.{rand}{input_path.suffix}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write as UTF-8 (normalized).
    data_out = text.encode("utf-8", errors="replace")
    with open(output_path, "wb") as f:
        f.write(data_out)
        f.flush()
        os.fsync(f.fileno())

    size_after = int(output_path.stat().st_size)
    sha_after = _sha256_file(output_path)

    return FilePreprocessResult(
        input_path=str(input_path),
        output_path=str(output_path),
        changed=True,
        size_before=size_before,
        size_after=size_after,
        sha256_before=sha_before,
        sha256_after=sha_after,
        steps=logs,
        warnings=warnings,
    )
