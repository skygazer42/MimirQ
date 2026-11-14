"""
ZIP image processor - extract images from ZIP and upload to MinIO.

Used for Markdown + images archives returned by MinerU/DeepDoc parsers.
"""

import io
import re
import shutil
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import settings
from app.parsing.utils.artifact_normalizer import choose_markdown_file
from app.rag.core.logging import get_logger
from app.storage.object.minio import minio_service

logger = get_logger("parsing.zip_processor")


def sanitize_zip_member(member_name: str) -> Path:
    """
    Convert a zip member name into a safe relative path.

    Rejects absolute paths and path traversal. Works cross-platform.
    """
    name = (member_name).replace("\\", "/").lstrip("/")
    posix = PurePosixPath(name)
    if not posix.parts:
        raise ValueError("Empty ZIP member name")
    if posix.is_absolute():
        raise ValueError(f"Absolute ZIP member path: {member_name}")
    if ".." in posix.parts:
        raise ValueError(f"Path traversal in ZIP member: {member_name}")
    # Windows drive letters like C:/
    first = posix.parts[0]
    if ":" in first:
        raise ValueError(f"Drive letter in ZIP member: {member_name}")
    return Path(*posix.parts)


def safe_extract_zip(zip_ref: zipfile.ZipFile, dest_dir: Path) -> None:
    """
    Extract a zip safely (zip-slip + basic zip-bomb limits).
    """
    infos = zip_ref.infolist()
    max_files = int(settings.ZIP_MAX_FILES)
    max_total = int(settings.ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES)
    max_single = int(settings.ZIP_MAX_SINGLE_UNCOMPRESSED_BYTES)

    if len(infos) > max_files:
        raise ValueError(f"ZIP contains too many files: {len(infos)} > {max_files}")

    total_bytes = 0
    for info in infos:
        total_bytes += info.file_size
        if info.file_size and info.file_size > max_single:
            raise ValueError(f"ZIP entry too large: {info.filename} ({info.file_size} bytes)")
    if total_bytes > max_total:
        raise ValueError(f"ZIP uncompressed size too large: {total_bytes} > {max_total}")

    dest_resolved = dest_dir.resolve()
    for info in infos:
        rel = sanitize_zip_member(info.filename)
        out_path = (dest_dir / rel).resolve()
        if dest_resolved != out_path and dest_resolved not in out_path.parents:
            raise ValueError(f"ZIP member escapes destination: {info.filename}")
        if info.is_dir():
            out_path.mkdir(parents=True, exist_ok=True)
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with zip_ref.open(info, "r") as src, open(out_path, "wb") as dst:
            shutil.copyfileobj(src, dst)


def normalize_zip_image_ref(raw: str) -> str:
    """
    Normalize markdown/html image path for dictionary lookup.
    Strips quotes/title fragments and leading './'.
    """
    val = (raw).strip()
    if not val:
        return ""
    if val.startswith("<") and ">" in val:
        val = val[1 : val.index(">")].strip()
    # Drop optional title: (path "title")
    if val.split(":", 1)[0].lower() not in {"http", "https"}:
        val = val.split()[0] if val.split() else val
    val = val.strip().strip('"').strip("'")
    val = val.split("#", 1)[0].split("?", 1)[0]
    val = val.replace("\\", "/")
    while val.startswith("./"):
        val = val[2:]
    return val


def _zip_result(markdown: str, images: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "markdown": markdown,
        "images": images,
        "image_count": len(images),
    }


def _extract_markdown_content(temp_path: Path) -> tuple[Path | None, str]:
    markdown_files = list(temp_path.rglob("*.md"))
    if not markdown_files:
        logger.warning("[zip] no markdown found in archive")
        return None, ""

    md_file = choose_markdown_file(markdown_files)
    logger.info("[zip] markdown=%s", md_file)
    return md_file, md_file.read_text(encoding="utf-8", errors="ignore")


def _find_image_files(temp_path: Path) -> list[Path]:
    image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
    image_files: list[Path] = []
    for path in temp_path.rglob("*"):
        if not path.is_file():
            continue
        parts_lower = [part.lower() for part in path.parts]
        if "__macosx" in parts_lower:
            continue
        if path.suffix.lower() in image_extensions:
            image_files.append(path)
    return image_files


def _limit_image_files(image_files: list[Path]) -> list[Path]:
    max_images = max(0, int(settings.ZIP_MAX_IMAGES or 0))
    if not max_images or len(image_files) <= max_images:
        return image_files
    logger.warning(
        "[zip] too many images in archive: %s > %s (extra images will be skipped)",
        len(image_files),
        max_images,
    )
    return image_files[:max_images]


def _image_relative_keys(*, img_file: Path, temp_path: Path, md_file: Path) -> tuple[list[str], str]:
    rel_keys: list[str] = []
    try:
        rel_root = img_file.relative_to(temp_path)
        rel_root_str = rel_root.as_posix()
        rel_keys.append(rel_root_str)
    except Exception:
        rel_root_str = img_file.name

    try:
        rel_md_str = img_file.relative_to(md_file.parent).as_posix()
        if rel_md_str not in rel_keys:
            rel_keys.append(rel_md_str)
    except Exception as exc:
        logger.debug("Ignoring ZIP image markdown-relative key failure: %s", exc)

    if img_file.name not in rel_keys:
        rel_keys.append(img_file.name)
    return rel_keys, rel_root_str


def _upload_zip_image_bytes(img_file: Path) -> bytes:
    from PIL import Image as PILImage

    with img_file.open("rb") as handle:
        img_raw = handle.read()
    with ExitStack() as cleanup:
        img = PILImage.open(io.BytesIO(img_raw))
        cleanup.callback(img.close)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
            cleanup.callback(img.close)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85, optimize=True)
        return out.getvalue()


def _upload_zip_image(
    *,
    idx: int,
    img_file: Path,
    rel_keys: list[str],
    rel_root_str: str,
    tenant_id: str | None,
    dataset_id: str,
    document_id: str,
    image_mapping: dict[str, dict[str, str]],
    uploaded_images: list[dict[str, str]],
) -> None:
    chunk_id = f"asset{idx}"
    img_data = _upload_zip_image_bytes(img_file)
    img_id = minio_service.upload_image(
        image_data=img_data,
        tenant_id=tenant_id or dataset_id,
        dataset_id=dataset_id,
        document_id=document_id,
        chunk_key=chunk_id,
        extension="jpg",
    )
    url = f"/api/v1/documents/image-url/{img_id}"

    for key in rel_keys:
        normalized = normalize_zip_image_ref(key)
        if normalized:
            image_mapping[normalized] = {"img_id": img_id, "url": url}

    uploaded_images.append(
        {
            "img_id": img_id,
            "original_path": rel_root_str,
            "url": url,
        }
    )
    logger.debug("[zip] uploaded image %s -> %s", rel_root_str, img_id)


def _upload_zip_images(
    *,
    image_files: list[Path],
    temp_path: Path,
    md_file: Path,
    tenant_id: str | None,
    dataset_id: str,
    document_id: str,
) -> tuple[dict[str, dict[str, str]], list[dict[str, str]]]:
    image_mapping: dict[str, dict[str, str]] = {}
    uploaded_images: list[dict[str, str]] = []
    if not settings.MINIO_ENABLED:
        return image_mapping, uploaded_images

    for idx, img_file in enumerate(image_files):
        rel_keys, rel_root_str = _image_relative_keys(
            img_file=img_file,
            temp_path=temp_path,
            md_file=md_file,
        )
        try:
            _upload_zip_image(
                idx=idx,
                img_file=img_file,
                rel_keys=rel_keys,
                rel_root_str=rel_root_str,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
                image_mapping=image_mapping,
                uploaded_images=uploaded_images,
            )
        except Exception as exc:
            logger.warning("[zip] failed uploading image %s: %s", img_file, exc)

    return image_mapping, uploaded_images


def process_zip_with_images(
    zip_path: Path,
    dataset_id: str,
    document_id: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Process a ZIP containing Markdown + images.

    Flow:
    1. Extract ZIP to a temp directory
    2. Find Markdown file
    3. Extract images and upload to MinIO
    4. Replace image refs in Markdown with MinIO URLs
    5. Return processed Markdown and image mapping

    Args:
        zip_path: ZIP file path.
        tenant_id: Tenant ID.
        dataset_id: Dataset ID.
        document_id: Document ID.

    Returns:
        {
            "markdown": "processed Markdown content",
            "images": [{"img_id": "...", "original_path": "...", "url": "..."}],
            "image_count": count
        }
    """
    with tempfile.TemporaryDirectory(prefix="zip_extract_") as temp_dir:
        temp_path = Path(temp_dir)
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            safe_extract_zip(zip_ref, temp_path)
        logger.info("[zip] extracted to %s", temp_path)

        md_file, markdown_content = _extract_markdown_content(temp_path)
        if md_file is None:
            return _zip_result("", [])

        image_files = _find_image_files(temp_path)
        if not image_files:
            logger.info("[zip] no images found in archive")
            return _zip_result(markdown_content, [])

        logger.info("[zip] images=%s", len(image_files))
        image_mapping, uploaded_images = _upload_zip_images(
            image_files=_limit_image_files(image_files),
            temp_path=temp_path,
            md_file=md_file,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
        )
        if image_mapping:
            markdown_content = replace_zip_image_refs(markdown_content, image_mapping)
            logger.info("[zip] replaced %s image refs", len(image_mapping))

        return _zip_result(markdown_content, uploaded_images)


def replace_zip_image_refs(markdown: str, image_mapping: dict[str, dict[str, str]]) -> str:
    """
    Replace image references in Markdown.

    Supported formats:
    - ![alt](path/to/image.png)
    - ![](./images/pic.jpg)
    - <img src="path/to/image.png">
    """

    # Replace Markdown syntax: ![alt](path)
    def replace_md_image(match):
        alt_text = match.group(1)
        raw = match.group(2)
        normalized_path = normalize_zip_image_ref(raw)

        if normalized_path and normalized_path in image_mapping:
            url = image_mapping[normalized_path].get("url")
            if not url:
                return match.group(0)
            return f"![{alt_text}]({url})"
        return match.group(0)

    markdown = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_md_image, markdown)

    # Replace HTML img tag: <img src="path">
    def replace_html_image(match):
        raw = match.group(1)
        normalized_path = normalize_zip_image_ref(raw)

        if normalized_path and normalized_path in image_mapping:
            url = image_mapping[normalized_path].get("url")
            if not url:
                return match.group(0)
            return f'<img src="{url}"'
        return match.group(0)

    markdown = re.sub(r'<img\s+src="([^"]+)"', replace_html_image, markdown)

    return markdown


class ZipImageProcessor:
    """Fixed interface consumed by preserved vendored DeepDoc source."""

    _safe_extract = staticmethod(safe_extract_zip)
    _sanitize_zip_member = staticmethod(sanitize_zip_member)


__all__ = [
    "ZipImageProcessor",
    "normalize_zip_image_ref",
    "process_zip_with_images",
    "replace_zip_image_refs",
    "safe_extract_zip",
    "sanitize_zip_member",
]
