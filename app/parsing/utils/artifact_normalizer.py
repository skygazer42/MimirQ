"""
Artifact normalizer for external parser outputs.

Many external parsers return a ZIP with arbitrary folder structures:
- Markdown can be nested in subfolders
- Images can be anywhere, referenced with relative paths

This helper normalizes an extracted directory into a stable layout:
- `result.md` at the root
- `images/` folder at the root (optional)
- Markdown image references rewritten to `images/<new_name>`
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.rag.core.logging import get_logger

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
logger = get_logger(__name__)
_ARTIFACT_NORMALIZATION_FALLBACK_LOG_MESSAGE = "Ignoring non-critical artifact normalization fallback failure: %s"


def _safe_direct_child(root: Path, name: str, *, field: str) -> Path:
    child = Path(str(name or "").strip())
    if child.is_absolute() or len(child.parts) != 1 or child.name in {"", ".", ".."}:
        raise ValueError(f"invalid {field}: {name}")
    resolved_root = root.resolve(strict=False)
    resolved_child = (resolved_root / child.name).resolve(strict=False)
    try:
        resolved_child.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {name}") from exc
    return resolved_child


def _choose_markdown_file(markdown_files: list[Path]) -> Path:
    preferred = {"output.md", "result.md", "index.md", "readme.md"}

    candidates: list[Path] = []
    for path in markdown_files:
        parts = [p.lower() for p in path.parts]
        if "__macosx" in parts:
            continue
        candidates.append(path)
    if not candidates:
        candidates = markdown_files

    for name in preferred:
        for path in candidates:
            if path.name.lower() == name:
                return path

    def sort_key(p: Path) -> tuple[int, int]:
        try:
            size = p.stat().st_size
        except Exception:
            size = 0
        return (len(p.parts), -int(size))

    candidates.sort(key=sort_key)
    return candidates[0]


def _iter_image_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = [p.lower() for p in path.parts]
        if "__macosx" in parts:
            continue
        if path.suffix.lower() in _IMAGE_EXTS:
            yield path


def _normalize_ref_path(raw: str) -> str:
    """
    Normalize markdown/html image path for dictionary lookup.

    - strips quotes/title fragments
    - strips leading './'
    - strips query/hash
    """
    val = (raw or "").strip()
    if not val:
        return ""
    # Drop optional title: (path "title")
    if val.split(":", 1)[0].lower() not in {"http", "https"}:
        val = val.split()[0] if val.split() else val
    val = val.strip().strip('"').strip("'")
    val = val.split("#", 1)[0].split("?", 1)[0]
    val = val.replace("\\", "/")
    while val.startswith("./"):
        val = val[2:]
    return val


def _skip_spaces(text: str, cursor: int) -> int:
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    return cursor


def _has_attribute_name_boundary(tag: str, name_start: int) -> bool:
    before = tag[name_start - 1] if name_start > 0 else " "
    return not (before.isalnum() or before in {"-", "_", ":"})


def _read_quoted_attribute_value(tag: str, quote_at: int) -> tuple[int, int, str] | None:
    if quote_at >= len(tag) or tag[quote_at] not in {"'", '"'}:
        return None
    quote = tag[quote_at]
    value_start = quote_at + 1
    value_end = tag.find(quote, value_start)
    if value_end < 0:
        return None
    return value_start, value_end, tag[value_start:value_end]


def _find_img_src_span(tag: str) -> tuple[int, int, str] | None:
    lower = tag.lower()
    pos = 0
    while True:
        src_at = lower.find("src", pos)
        if src_at < 0:
            return None
        pos = src_at + 3
        if not _has_attribute_name_boundary(tag, src_at):
            continue
        eq_at = _skip_spaces(tag, pos)
        if eq_at >= len(tag) or tag[eq_at] != "=":
            continue
        src_span = _read_quoted_attribute_value(tag, _skip_spaces(tag, eq_at + 1))
        if src_span:
            return src_span


def rewrite_html_image_refs(text: str, resolver: Any) -> str:
    """Rewrite quoted src values inside HTML img tags using a linear scan."""
    source = str(text or "")
    lower = source.lower()
    out: list[str] = []
    cursor = 0
    while True:
        start = lower.find("<img", cursor)
        if start < 0:
            out.append(source[cursor:])
            break
        out.append(source[cursor:start])
        end = source.find(">", start + 4)
        if end < 0:
            out.append(source[start:])
            break
        tag = source[start : end + 1]
        src_span = _find_img_src_span(tag)
        if not src_span:
            out.append(tag)
            cursor = end + 1
            continue
        value_start, value_end, raw_path = src_span
        new_path = resolver(raw_path)
        if new_path:
            out.append(f"{tag[:value_start]}{new_path}{tag[value_end:]}")
        else:
            out.append(tag)
        cursor = end + 1
    return "".join(out)


def normalize_extracted_artifacts(
    extract_root: Path,
    *,
    output_markdown_name: str = "result.md",
    output_image_dir: str = "images",
) -> dict[str, Any]:
    """
    Normalize an extracted external-parser output directory in-place.

    Returns:
      {
        "markdown_file": Path|None,
        "image_dir": Path,
        "image_count": int,
        "mapping": { "<original_key>": "images/<new_name>" }
      }
    """
    root = Path(extract_root).resolve(strict=False)
    if not root.exists():
        raise FileNotFoundError(str(root))

    md_files = list(root.rglob("*.md"))
    if not md_files:
        return {
            "markdown_file": None,
            "image_dir": _safe_direct_child(root, output_image_dir, field="output_image_dir"),
            "image_count": 0,
            "mapping": {},
        }

    md_file = _choose_markdown_file(md_files)
    md_text = md_file.read_text(encoding="utf-8", errors="ignore")

    image_dir = _safe_direct_child(root, output_image_dir, field="output_image_dir")
    image_dir.mkdir(exist_ok=True)

    images = sorted(_iter_image_files(root), key=lambda p: p.as_posix())
    mapping: dict[str, str] = {}

    counter = 1
    for img in images:
        # Skip already-normalized images.
        try:
            img.relative_to(image_dir)
            continue
        except Exception as exc:
            logger.debug(_ARTIFACT_NORMALIZATION_FALLBACK_LOG_MESSAGE, exc)

        new_name = f"image_{counter:03d}{img.suffix.lower()}"
        new_rel = f"{output_image_dir}/{new_name}"
        new_path = image_dir / new_name

        # Multiple keys to match common reference habits.
        keys: list[str] = []
        try:
            keys.append(img.relative_to(root).as_posix())
        except Exception as exc:
            logger.debug(_ARTIFACT_NORMALIZATION_FALLBACK_LOG_MESSAGE, exc)
        try:
            keys.append(img.relative_to(md_file.parent).as_posix())
        except Exception as exc:
            logger.debug(_ARTIFACT_NORMALIZATION_FALLBACK_LOG_MESSAGE, exc)
        keys.append(img.name)

        # Move (best-effort).
        try:
            shutil.move(str(img), str(new_path))
        except Exception:
            # If move fails (e.g. cross-device), fall back to copy.
            shutil.copy2(img, new_path)

        for k in keys:
            k2 = _normalize_ref_path(k)
            if k2 and k2 not in mapping:
                mapping[k2] = new_rel
        counter += 1

    if mapping:
        md_img_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"

        def _replace_md(m: re.Match) -> str:
            alt = m.group(1)
            raw_path = m.group(2)
            key = _normalize_ref_path(raw_path)
            new_rel = mapping.get(key) or mapping.get(Path(key).name)
            if new_rel:
                return f"![{alt}]({new_rel})"
            return m.group(0)

        def _resolve_html_src(raw_path: str) -> str | None:
            key = _normalize_ref_path(raw_path)
            new_rel = mapping.get(key) or mapping.get(Path(key).name)
            if new_rel:
                return new_rel
            return None

        md_text = re.sub(md_img_pattern, _replace_md, md_text)
        md_text = rewrite_html_image_refs(md_text, _resolve_html_src)

    out_md = _safe_direct_child(root, output_markdown_name, field="output_markdown_name")
    # Output filename is validated as a direct child of the extraction root.
    out_md.write_text(md_text.strip() + "\n", encoding="utf-8")  # NOSONAR

    return {
        "markdown_file": out_md,
        "image_dir": image_dir,
        "image_count": counter - 1,
        "mapping": mapping,
    }


__all__ = [
    "normalize_extracted_artifacts",
    "rewrite_html_image_refs",
]
