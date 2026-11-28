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

import logging
import os
import re
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypedDict

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
_HTML_IMG_RE = re.compile(r"""<img(?=[\s/>])(?:[^<>"']|"[^"]*"|'[^']*')*>""", re.IGNORECASE)
_HTML_ATTRIBUTE_RE = re.compile(
    r"""(?P<name>[^\s"'=/>]+)(?:\s*=\s*(?:(?P<quote>["'])(?P<value>.*?)(?P=quote)|[^\s"'=<>`]+))?""",
    re.DOTALL,
)
logger = logging.getLogger(__name__)


class _ArtifactNormalizationResult(TypedDict):
    markdown_file: Path | None
    image_dir: Path
    image_count: int
    mapping: dict[str, str]


def sanitize_artifact_run_id(value: str, *, fallback: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip() or fallback)[:120]
    if text in {"", ".", ".."}:
        raise ValueError("Parser artifact run id must be a child directory name")
    return text


def _safe_direct_child(root: Path, name: str, *, field: str) -> Path:
    child = Path(name.strip())
    if child.is_absolute() or len(child.parts) != 1 or child.name in {"", ".", ".."}:
        raise ValueError(f"invalid {field}: {name}")
    resolved_root = root.resolve(strict=False)
    resolved_child = (resolved_root / child.name).resolve(strict=False)
    try:
        resolved_child.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"invalid {field}: {name}") from exc
    return resolved_child


def choose_markdown_file(markdown_files: list[Path]) -> Path:
    preferred = ("output.md", "result.md", "index.md", "readme.md")

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
        except OSError as exc:
            logger.debug("Could not stat Markdown candidate %s: %s", p, exc)
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


def _normalize_ref_path(raw: str, *, literal: bool = False) -> str:
    """
    Normalize markdown/html image path for dictionary lookup.

    - strips quotes/title fragments
    - strips leading './'
    - strips query/hash
    """
    val = (raw).strip()
    if not val:
        return ""
    if not literal:
        if val.startswith("<") and ">" in val:
            val = val[1 : val.index(">")]
        elif val.split(":", 1)[0].lower() not in {"http", "https"}:
            val = val.split(maxsplit=1)[0]
    val = val.strip().strip('"').strip("'")
    val = val.split("#", 1)[0].split("?", 1)[0]
    val = val.replace("\\", "/")
    while val.startswith("./"):
        val = val[2:]
    return val


def _find_img_src_span(tag: str) -> tuple[int, int, str] | None:
    for attribute in _HTML_ATTRIBUTE_RE.finditer(tag, 4):
        if attribute.group("name").lower() == "src" and attribute.group("value") is not None:
            start, end = attribute.span("value")
            return start, end, attribute.group("value")
    return None


def rewrite_html_image_refs(text: str, resolver: Callable[[str], str | None]) -> str:
    """Rewrite quoted src values while retaining the original HTML spelling."""

    def replace(match: re.Match[str]) -> str:
        tag = match.group()
        src_span = _find_img_src_span(tag)
        if src_span is None:
            return tag
        value_start, value_end, raw_path = src_span
        new_path = resolver(raw_path)
        return f"{tag[:value_start]}{new_path}{tag[value_end:]}" if new_path else tag

    return _HTML_IMG_RE.sub(replace, text)


def _artifact_mapping_keys(img: Path, *, root_path: Path, markdown_parent: Path) -> list[str]:
    return [
        img.relative_to(root_path).as_posix(),
        Path(os.path.relpath(img, markdown_parent)).as_posix(),
        img.name,
    ]


def _move_or_copy_artifact_image(img: Path, new_path: Path) -> None:
    try:
        shutil.move(str(img), str(new_path))
    except OSError:
        # If move fails (e.g. cross-device), fall back to copy.
        shutil.copy2(img, new_path)


def _rewrite_artifact_markdown_refs(md_text: str, *, mapping: dict[str, str]) -> str:
    md_img_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"

    def _resolve_ref(raw_path: str, *, literal: bool = False) -> str | None:
        key = _normalize_ref_path(raw_path, literal=literal)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", key) or key.startswith("//"):
            return None
        return mapping.get(key) or mapping.get(Path(key).name)

    def _replace_md(m: re.Match) -> str:
        alt = m.group(1)
        new_rel = _resolve_ref(m.group(2))
        if new_rel:
            return f"![{alt}]({new_rel})"
        return m.group(0)

    rewritten = re.sub(md_img_pattern, _replace_md, md_text)
    return rewrite_html_image_refs(rewritten, lambda raw_path: _resolve_ref(raw_path, literal=True))


def normalize_extracted_artifacts(
    extract_root: Path,
    *,
    output_markdown_name: str = "result.md",
    output_image_dir: str = "images",
) -> _ArtifactNormalizationResult:
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

    md_file = choose_markdown_file(md_files)
    md_text = md_file.read_text(encoding="utf-8")

    image_dir = _safe_direct_child(root, output_image_dir, field="output_image_dir")
    image_dir.mkdir(exist_ok=True)

    images = sorted(_iter_image_files(root), key=lambda p: p.as_posix())
    mapping: dict[str, str] = {}

    counter = 1
    for img in images:
        keys = _artifact_mapping_keys(img, root_path=root, markdown_parent=md_file.parent)
        if img.is_relative_to(image_dir):
            new_rel = img.relative_to(root).as_posix()
        else:
            while True:
                new_name = f"image_{counter:03d}{img.suffix.lower()}"
                counter += 1
                new_path = image_dir / new_name
                if not new_path.exists():
                    break
            new_rel = new_path.relative_to(root).as_posix()
            _move_or_copy_artifact_image(img, new_path)
        for key in keys:
            normalized = _normalize_ref_path(key, literal=True)
            if normalized and normalized not in mapping:
                mapping[normalized] = new_rel

    if mapping:
        md_text = _rewrite_artifact_markdown_refs(md_text, mapping=mapping)

    out_md = _safe_direct_child(root, output_markdown_name, field="output_markdown_name")
    # Output filename is validated as a direct child of the extraction root.
    out_md.write_text(md_text.strip() + "\n", encoding="utf-8")  # NOSONAR

    return {
        "markdown_file": out_md,
        "image_dir": image_dir,
        "image_count": len(images),
        "mapping": mapping,
    }


__all__ = [
    "choose_markdown_file",
    "normalize_extracted_artifacts",
    "rewrite_html_image_refs",
    "sanitize_artifact_run_id",
]
