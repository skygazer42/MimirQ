"""
Metadata normalization utilities.

Goals:
- Normalize metadata across different parser/chunker outputs for compatibility
- Avoid scattered business logic with "patch-style handling" across multiple modules
"""

import re
import uuid
from typing import Any

_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def _looks_like_uuid(value: str) -> bool:
    s = str(value or "").strip()
    if not s:
        return False
    try:
        uuid.UUID(s)
        return True
    except Exception:
        return False


def _looks_like_local_image_id(value: str) -> bool:
    """
    Local image ids are stored under {UPLOAD_DIR}/{tenant}/images/{image_id}.ext.

    documents.py allows both UUID and 32-hex ids (UUID without hyphens).
    """
    s = str(value or "").strip()
    if not s:
        return False
    return _looks_like_uuid(s) or bool(_HEX32_RE.match(s))


def _looks_like_minio_img_id(value: str) -> bool:
    """
    MinIO img_id formats supported by /api/v1/documents/image-url/{img_id}:
    - "{tenant_id}:{dataset_id}:{document_id}:{chunk_key}"
    - Back-compat: "{dataset_id}-{chunk_id}"

    We keep this strict to avoid generating broken image_url values.
    """
    s = str(value or "").strip()
    if not s:
        return False

    if ":" in s:
        parts = s.split(":", 3)
        if len(parts) != 4:
            return False
        tenant_part, dataset_part, document_part, chunk_key = parts
        if not chunk_key.strip():
            return False
        return _looks_like_uuid(tenant_part) and _looks_like_uuid(dataset_part) and _looks_like_uuid(document_part)

    if "-" in s:
        dataset_part = s.split("-", 1)[0]
        return _looks_like_uuid(dataset_part)

    return False


def normalize_image_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize image-related fields:
    - img_id / image_id
    - img_url / image_url

    Conventions:
    - Preserve original fields (no forced deletion), only fill in missing standard fields
    - Standard field priority: image_* takes precedence, followed by img_*
    """
    if not isinstance(meta, dict):
        return {}

    img_id = meta.get("img_id")
    image_id = meta.get("image_id")
    if not image_id and img_id:
        meta["image_id"] = img_id
    if not img_id and image_id:
        meta["img_id"] = image_id

    img_url = meta.get("img_url")
    image_url = meta.get("image_url")
    if not image_url and img_url:
        meta["image_url"] = img_url
    if not img_url and image_url:
        meta["img_url"] = image_url

    # Derive URL from id when missing. This improves UI citations for figure/image chunks.
    #
    # IMPORTANT:
    # - Only emit image-url for MinIO-style ids; local ids must use the /documents/image/{image_id} endpoint.
    # - Keep it best-effort; do not override existing URLs.
    if not meta.get("image_url") and not meta.get("img_url"):
        eff_img_id = meta.get("img_id")
        if isinstance(eff_img_id, str) and _looks_like_minio_img_id(eff_img_id):
            url = f"/api/v1/documents/image-url/{eff_img_id.strip()}"
            meta.setdefault("image_url", url)
            meta.setdefault("img_url", url)
        else:
            eff_image_id = meta.get("image_id")
            if isinstance(eff_image_id, str) and _looks_like_local_image_id(eff_image_id):
                url = f"/api/v1/documents/image/{eff_image_id.strip()}"
                meta.setdefault("image_url", url)
                meta.setdefault("img_url", url)

    return meta


_LIST_BULLET_RE = re.compile(r"^[-*+•]\s+\S")
_LIST_ORDERED_RE = re.compile(r"^\d{1,3}[.)]\s+\S")


def _leading_indent_level(line: str) -> int:
    indent = 0
    for ch in line:
        if ch == " ":
            indent += 1
            continue
        if ch == "\t":
            indent += 4
            continue
        break
    return min(indent // 2, 50)


def infer_chunk_structure(meta: dict[str, Any], content: str) -> dict[str, Any]:
    """
    Infer lightweight structure signals for retrieval/reranking.

    Output fields (when present):
    - structure.list: {item_count, min_level, max_level}
    - structure.table: {title, sheet_name}

    Design goals:
    - Best-effort only (no hard failures)
    - Small and deterministic
    """
    if not isinstance(meta, dict):
        return {}

    structure = meta.get("structure")
    if isinstance(structure, dict):
        structure = dict(structure)
    else:
        structure = {}

    text = str(content or "")
    if text:
        item_count = 0
        min_level: int | None = None
        max_level: int | None = None
        for line in text.splitlines():
            if not line or not line.strip():
                continue
            stripped = line.lstrip(" \t")
            if not stripped:
                continue
            if not (_LIST_BULLET_RE.match(stripped) or _LIST_ORDERED_RE.match(stripped)):
                continue
            level = _leading_indent_level(line)
            item_count += 1
            min_level = level if min_level is None else min(min_level, level)
            max_level = level if max_level is None else max(max_level, level)
            if item_count >= 2000:
                break
        if item_count > 0 and min_level is not None and max_level is not None:
            structure["list"] = {
                "item_count": int(item_count),
                "min_level": int(min_level),
                "max_level": int(max_level),
            }

    table: dict[str, Any] = {}
    sheet_name = meta.get("sheet_name")
    if isinstance(sheet_name, str) and sheet_name.strip():
        sn = sheet_name.strip()
        if sn and sn != "_meta":
            table["sheet_name"] = sn[:200]

    title: str | None = None
    for key in ("table_title", "table_header", "header_path"):
        v = meta.get(key)
        if isinstance(v, str) and v.strip():
            title = v.strip()
            break
    if not title and isinstance(table.get("sheet_name"), str) and str(table.get("sheet_name") or "").strip():
        title = str(table.get("sheet_name")).strip()
    if title:
        table["title"] = title[:200]

    if table:
        structure["table"] = table

    if structure:
        meta["structure"] = structure
    return meta


def normalize_section_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize section/title metadata across chunkers.

    Standard fields:
    - header_path: a lightweight string path used for citations/embedding context
    - outline_path: optional list[str] for outline-aware chunkers
    - outline_path_str: optional string form of outline_path
    """
    if not isinstance(meta, dict):
        return {}

    header_path = meta.get("header_path")
    if isinstance(header_path, str) and header_path.strip():
        return meta

    outline_path_str = meta.get("outline_path_str")
    if isinstance(outline_path_str, str) and outline_path_str.strip():
        meta["header_path"] = outline_path_str.strip()
        return meta

    outline_path = meta.get("outline_path")
    if isinstance(outline_path, list) and outline_path:
        parts = [str(x).strip() for x in outline_path if str(x).strip()]
        if parts:
            meta["outline_path"] = parts
            meta.setdefault("outline_path_str", " / ".join(parts))
            outline_path_str2 = meta.get("outline_path_str")
            if isinstance(outline_path_str2, str) and outline_path_str2.strip():
                meta["header_path"] = outline_path_str2.strip()
                return meta

    header_context = meta.get("header_context")
    if isinstance(header_context, str) and header_context.strip():
        meta["header_path"] = header_context.strip()
        return meta

    minutes_title = meta.get("minutes_section_title")
    if isinstance(minutes_title, str) and minutes_title.strip():
        meta["header_path"] = minutes_title.strip()[:200]
        return meta

    sheet_name = meta.get("sheet_name")
    if isinstance(sheet_name, str) and sheet_name.strip():
        sn = sheet_name.strip()
        if sn and sn != "_meta":
            meta["header_path"] = sn[:200]
            return meta

    table_title = meta.get("table_title")
    if isinstance(table_title, str) and table_title.strip():
        meta["header_path"] = table_title.strip()[:200]
        return meta

    # LangChain MarkdownHeaderTextSplitter metadata keys: header_1..header_6.
    parts = []
    for i in range(1, 7):
        v = meta.get(f"header_{i}")
        if v is None:
            continue
        s = str(v).strip()
        if s:
            parts.append(s)
    if parts:
        meta["header_path"] = " > ".join(parts)

    return meta


__all__ = ["infer_chunk_structure", "normalize_image_metadata", "normalize_section_metadata"]
