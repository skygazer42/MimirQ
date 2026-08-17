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


import hashlib
import os
import re
import time
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.optional_deps import optional_import
from app.rag.core.logging import get_logger

logger = get_logger(__name__)
_HTML_EXT = ".html"
_SKIPPED_NOT_HTML_NOTE = "skipped (not html)"

TEXT_LIKE_EXTS = {
    ".txt",
    ".md",
    ".rst",
    ".adoc",
    ".csv",
    ".json",
    _HTML_EXT,
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

_HTML_EXTS = {_HTML_EXT, ".htm"}


def _result_unchanged(
    *,
    input_path: Path,
    size_before: int,
    sha_before: str,
    logs: list[PreprocessStepLog],
    warnings: list[str],
) -> FilePreprocessResult:
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


def _skip_result(
    *,
    input_path: Path,
    steps: list[dict[str, Any]],
    size_before: int,
    sha_before: str,
    warnings: list[str],
    note: str,
) -> FilePreprocessResult:
    logs = [
        PreprocessStepLog(
            id=str((step or {}).get("id") or ""),
            applied=False,
            changed=False,
            note=note,
        )
        for step in steps
    ]
    return _result_unchanged(
        input_path=input_path,
        size_before=size_before,
        sha_before=sha_before,
        logs=logs,
        warnings=warnings,
    )


def _output_path_for_preprocess(input_path: Path, output_path: Path | None) -> Path:
    if output_path is not None:
        return Path(output_path)
    rand = uuid.uuid4().hex[:10]
    return input_path.with_name(f"{input_path.stem}.pre.{rand}{input_path.suffix}")


def _apply_transform(text: str, transform: Callable[[str], str]) -> tuple[str, bool]:
    new_text = transform(text)
    return new_text, new_text != text


def _apply_html_transform(text: str, *, ext: str, transform: Callable[[str], str]) -> tuple[str, bool, str]:
    if ext not in _HTML_EXTS:
        return text, False, _SKIPPED_NOT_HTML_NOTE
    new_text, changed = _apply_transform(text, transform)
    return new_text, changed, ""


def _step_reencode_utf8(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = ext
    return text, True, False, f"encoding={enc} conf={conf:.2f}"


def _step_strip_bom(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (ext, enc, conf)
    new_text = text.lstrip("\ufeff") if text.startswith("\ufeff") else text
    return new_text, True, new_text != text, ""


def _step_normalize_newlines(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (ext, enc, conf)
    new_text, changed = _apply_transform(text, lambda value: value.replace("\r\n", "\n").replace("\r", "\n"))
    return new_text, True, changed, ""


def _collapse_blank_lines(text: str) -> str:
    new_text = text
    while "\n\n\n" in new_text:
        new_text = new_text.replace("\n\n\n", "\n\n")
    return new_text


def _step_collapse_blank_lines(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (ext, enc, conf)
    new_text, changed = _apply_transform(text, _collapse_blank_lines)
    return new_text, True, changed, ""


def _step_trim_trailing_whitespace(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (ext, enc, conf)
    new_text, changed = _apply_transform(text, lambda value: "\n".join(line.rstrip(" \t") for line in value.split("\n")))
    return new_text, True, changed, ""


def _step_remove_zero_width(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (ext, enc, conf)
    new_text, changed = _apply_transform(text, lambda value: re.sub(r"[\u200b\u200c\u200d\u2060\u00ad\ufeff]", "", value))
    return new_text, True, changed, ""


def _step_remove_control_chars(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (ext, enc, conf)
    new_text, changed = _apply_transform(text, lambda value: re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value))
    return new_text, True, changed, ""


def _step_unicode_nfc(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (ext, enc, conf)
    new_text, changed = _apply_transform(text, lambda value: unicodedata.normalize("NFC", value))
    return new_text, True, changed, ""


def _step_unicode_nfkc(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (ext, enc, conf)
    new_text, changed = _apply_transform(text, lambda value: unicodedata.normalize("NFKC", value))
    return new_text, True, changed, ""


def _step_strip_scripts_styles(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (enc, conf)
    new_text, changed, note = _apply_html_transform(text, ext=ext, transform=lambda value: _RE_SCRIPT_STYLE.sub("", value))
    return new_text, True, changed, note


def _step_strip_comments(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (enc, conf)
    new_text, changed, note = _apply_html_transform(text, ext=ext, transform=lambda value: _RE_HTML_COMMENT.sub("", value))
    return new_text, True, changed, note


def _step_strip_boilerplate_tags(text: str, *, ext: str, enc: str, conf: float) -> tuple[str, bool, bool, str]:
    _ = (enc, conf)
    new_text, changed, note = _apply_html_transform(
        text,
        ext=ext,
        transform=lambda value: _RE_HTML_BOILERPLATE_TAGS.sub("", value),
    )
    return new_text, True, changed, note


_STEP_HANDLERS = {
    "text.reencode_utf8": _step_reencode_utf8,
    "text.strip_bom": _step_strip_bom,
    "text.normalize_newlines": _step_normalize_newlines,
    "text.collapse_blank_lines": _step_collapse_blank_lines,
    "text.trim_trailing_whitespace": _step_trim_trailing_whitespace,
    "text.remove_zero_width": _step_remove_zero_width,
    "text.remove_control_chars": _step_remove_control_chars,
    "text.normalize_unicode_nfc": _step_unicode_nfc,
    "text.normalize_unicode_nfkc": _step_unicode_nfkc,
    "html.strip_scripts_styles": _step_strip_scripts_styles,
    "html.strip_comments": _step_strip_comments,
    "html.strip_boilerplate_tags": _step_strip_boilerplate_tags,
}


def _apply_preprocess_step(
    *,
    text: str,
    sid: str,
    ext: str,
    enc: str,
    conf: float,
) -> tuple[str, bool, bool, str]:
    handler = _STEP_HANDLERS.get(sid)
    if handler is None:
        return text, False, False, "skipped (unknown)"
    return handler(text, ext=ext, enc=enc, conf=conf)


def _write_preprocessed_text(*, output_path: Path, text: str) -> tuple[int, str]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data_out = text.encode("utf-8", errors="replace")
    with open(output_path, "wb") as f:
        f.write(data_out)
        f.flush()
        os.fsync(f.fileno())
    return int(output_path.stat().st_size), _sha256_file(output_path)


def _utf8_byte_len(text: str) -> int:
    try:
        return len(text.encode("utf-8", errors="replace"))
    except Exception:
        return int(len(text or ""))


def _apply_preprocess_steps(
    *,
    text: str,
    steps: list[dict[str, Any]],
    ext: str,
    enc: str,
    conf: float,
) -> tuple[str, list[PreprocessStepLog], bool]:
    changed_any = False
    logs: list[PreprocessStepLog] = []
    current_bytes = _utf8_byte_len(text)
    for step in steps:
        step_t0 = time.perf_counter()
        sid = str((step or {}).get("id") or "").strip().lower()
        bytes_before = int(current_bytes)
        text, applied, changed, note = _apply_preprocess_step(
            text=text,
            sid=sid,
            ext=ext,
            enc=enc,
            conf=conf,
        )
        if changed:
            changed_any = True
            current_bytes = _utf8_byte_len(text)
        bytes_after = int(current_bytes)
        elapsed_ms = max(0, int(round((time.perf_counter() - step_t0) * 1000)))
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
    return text, logs, changed_any


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
        return _result_unchanged(
            input_path=input_path,
            size_before=size_before,
            sha_before=sha_before,
            logs=[],
            warnings=[],
        )

    is_text_like = ext in TEXT_LIKE_EXTS
    if not is_text_like:
        return _skip_result(
            input_path=input_path,
            steps=steps,
            size_before=size_before,
            sha_before=sha_before,
            warnings=["non_text_file_skipped"],
            note="skipped (non-text file)",
        )

    raw, truncated = _read_bytes_bounded(input_path, max_bytes=max_text_bytes)
    if truncated:
        warnings.append(f"text_too_large_skipped(max={max_text_bytes})")
        return _skip_result(
            input_path=input_path,
            steps=steps,
            size_before=size_before,
            sha_before=sha_before,
            warnings=warnings,
            note="skipped (too large)",
        )

    enc, conf = _detect_encoding(raw)
    try:
        text = raw.decode(enc, errors="replace")
    except Exception:
        text = raw.decode("utf-8", errors="replace")
        enc = "utf-8"
        conf = 0.0

    original_text = text
    text, logs, changed_any = _apply_preprocess_steps(
        text=text,
        steps=steps,
        ext=ext,
        enc=enc,
        conf=conf,
    )

    if text == original_text:
        changed_any = False

    if not changed_any:
        return _result_unchanged(
            input_path=input_path,
            size_before=size_before,
            sha_before=sha_before,
            logs=logs,
            warnings=warnings,
        )

    output_path = _output_path_for_preprocess(input_path, output_path)
    size_after, sha_after = _write_preprocessed_text(output_path=output_path, text=text)

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
