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
    if not (val.startswith("http://") or val.startswith("https://")):
        val = val.split()[0] if val.split() else val
    val = val.strip().strip('"').strip("'")
    val = val.split("#", 1)[0].split("?", 1)[0]
    val = val.replace("\\", "/")
    while val.startswith("./"):
        val = val[2:]
    return val


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
    root = Path(extract_root)
    if not root.exists():
        raise FileNotFoundError(str(root))

    md_files = list(root.rglob("*.md"))
    if not md_files:
        return {
            "markdown_file": None,
            "image_dir": (root / output_image_dir),
            "image_count": 0,
            "mapping": {},
        }

    md_file = _choose_markdown_file(md_files)
    md_text = md_file.read_text(encoding="utf-8", errors="ignore")

    image_dir = root / output_image_dir
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
            logger.debug("Ignoring non-critical artifact normalization fallback failure: %s", exc)

        new_name = f"image_{counter:03d}{img.suffix.lower()}"
        new_rel = f"{output_image_dir}/{new_name}"
        new_path = image_dir / new_name

        # Multiple keys to match common reference habits.
        keys: list[str] = []
        try:
            keys.append(img.relative_to(root).as_posix())
        except Exception as exc:
            logger.debug("Ignoring non-critical artifact normalization fallback failure: %s", exc)
        try:
            keys.append(img.relative_to(md_file.parent).as_posix())
        except Exception as exc:
            logger.debug("Ignoring non-critical artifact normalization fallback failure: %s", exc)
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

        html_img_pattern = r'<img\s+([^>]*\s+)?src="([^"]+)"([^>]*)>'

        def _replace_html(m: re.Match) -> str:
            before = m.group(1) or ""
            raw_path = m.group(2)
            after = m.group(3) or ""
            key = _normalize_ref_path(raw_path)
            new_rel = mapping.get(key) or mapping.get(Path(key).name)
            if new_rel:
                return f'<img {before}src="{new_rel}"{after}>'
            return m.group(0)

        md_text = re.sub(md_img_pattern, _replace_md, md_text)
        md_text = re.sub(html_img_pattern, _replace_html, md_text)

    out_md = root / output_markdown_name
    out_md.write_text(md_text.strip() + "\n", encoding="utf-8")

    return {
        "markdown_file": out_md,
        "image_dir": image_dir,
        "image_count": counter - 1,
        "mapping": mapping,
    }


__all__ = [
    "normalize_extracted_artifacts",
]
