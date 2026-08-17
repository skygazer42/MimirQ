"""
Metadata normalization utilities.

Goals:
- Normalize metadata across different parser/chunker outputs for compatibility
- Avoid scattered business logic with "patch-style handling" across multiple modules
"""

import re
import uuid
from typing import Any

from app.rag.core.hashing import stable_hash

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


def _list_item_indent_level(line: str) -> int | None:
    if not line or not line.strip():
        return None
    stripped = line.lstrip(" \t")
    if not stripped:
        return None
    if not (_LIST_BULLET_RE.match(stripped) or _LIST_ORDERED_RE.match(stripped)):
        return None
    return _leading_indent_level(line)


def _infer_list_structure(content: str) -> dict[str, int] | None:
    levels: list[int] = []
    for line in str(content or "").splitlines():
        level = _list_item_indent_level(line)
        if level is None:
            continue
        levels.append(level)
        if len(levels) >= 2000:
            break
    if not levels:
        return None
    return {
        "item_count": len(levels),
        "min_level": min(levels),
        "max_level": max(levels),
    }


def _trimmed_metadata_text(meta: dict[str, Any], key: str) -> str | None:
    value = meta.get(key)
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _stringified_metadata_text(meta: dict[str, Any], key: str) -> str | None:
    value = meta.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_metadata_text(meta: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        text = _trimmed_metadata_text(meta, key)
        if text:
            return text
    return None


def _infer_table_structure(meta: dict[str, Any]) -> dict[str, str] | None:
    table: dict[str, str] = {}
    sheet_name = _trimmed_metadata_text(meta, "sheet_name")
    if sheet_name and sheet_name != "_meta":
        table["sheet_name"] = sheet_name[:200]

    title = _first_metadata_text(meta, ("table_title", "table_header", "header_path"))
    if not title:
        title = table.get("sheet_name")
    if title:
        table["title"] = title[:200]
    return table or None


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

    list_structure = _infer_list_structure(content)
    if list_structure:
        structure["list"] = list_structure

    table_structure = _infer_table_structure(meta)
    if table_structure:
        structure["table"] = table_structure

    if structure:
        meta["structure"] = structure
    return meta


def _header_path_from_outline(meta: dict[str, Any]) -> str | None:
    outline_path_str = _trimmed_metadata_text(meta, "outline_path_str")
    if outline_path_str:
        return outline_path_str

    outline_path = meta.get("outline_path")
    if not isinstance(outline_path, list) or not outline_path:
        return None
    parts = [str(item).strip() for item in outline_path if str(item).strip()]
    if not parts:
        return None
    meta["outline_path"] = parts
    meta.setdefault("outline_path_str", " / ".join(parts))
    return _trimmed_metadata_text(meta, "outline_path_str")


def _fallback_section_header(meta: dict[str, Any]) -> str | None:
    header_context = _trimmed_metadata_text(meta, "header_context")
    if header_context:
        return header_context

    minutes_title = _trimmed_metadata_text(meta, "minutes_section_title")
    if minutes_title:
        return minutes_title[:200]

    sheet_name = _trimmed_metadata_text(meta, "sheet_name")
    if sheet_name and sheet_name != "_meta":
        return sheet_name[:200]

    table_title = _trimmed_metadata_text(meta, "table_title")
    if table_title:
        return table_title[:200]

    parts = [
        value
        for index in range(1, 7)
        if (value := _stringified_metadata_text(meta, f"header_{index}"))
    ]
    return " > ".join(parts) or None


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

    if _trimmed_metadata_text(meta, "header_path"):
        return meta

    header_path = _header_path_from_outline(meta) or _fallback_section_header(meta)
    if header_path:
        meta["header_path"] = header_path

    return meta


def _hierarchy_parent_key(meta: dict[str, Any]) -> str:
    if "hierarchy_parent_key" in meta:
        raw_parent_key = meta.get("hierarchy_parent_key")
    else:
        raw_parent_key = meta.get("parent_id") or meta.get("parent_node_id")
    return str(raw_parent_key or "").strip()


def _hierarchy_level(meta: dict[str, Any], parent_key: str) -> str:
    level = str(meta.get("hierarchy_level") or "").strip().lower()
    if level:
        return level
    role = str(meta.get("chunk_role") or "").strip().lower()
    if role in {"parent", "child", "paragraph", "sentence"}:
        return role
    return "child" if parent_key else "chunk"


def _hierarchy_basis(meta: dict[str, Any]) -> str:
    basis = str(meta.get("hierarchy_basis") or "").strip().lower()
    if basis:
        return basis
    strategy = str(meta.get("chunk_strategy") or "").strip().lower()
    if strategy == "parent_child":
        return "parent_child"
    if strategy == "hierarchical_markdown":
        return "markdown_structure"
    return "chunk_sequence"


def _hierarchy_family_key(
    meta: dict[str, Any],
    *,
    document_id: str,
    parent_key: str,
    node_key: str,
) -> str:
    family_key = str(meta.get("hierarchy_family_key") or "").strip()
    if family_key:
        return family_key
    if parent_key:
        return stable_hash(f"hf:{document_id}:{parent_key}", length=32)
    return node_key


def _nonnegative_index(value: Any) -> int | None:
    try:
        index = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    return index if index is not None and index >= 0 else None


def _set_adjacent_hierarchy_metadata(
    meta: dict[str, Any],
    *,
    direction: str,
    document_id: str,
    default_index: int | None,
) -> None:
    index_key = f"{direction}_chunk_index"
    chunk_key = f"{direction}_chunk_key"
    sibling_key = f"hierarchy_{direction}_sibling_key"
    raw_index = meta.get(index_key)
    index = _nonnegative_index(default_index if raw_index is None else raw_index)
    if index is None:
        meta.setdefault(sibling_key, None)
        return

    meta.setdefault(index_key, index)
    key = str(meta.get(chunk_key) or "").strip()
    if not key and document_id:
        key = f"{document_id}:{index}"
    if key:
        meta.setdefault(chunk_key, key)
        meta.setdefault(sibling_key, key)


def ensure_hierarchy_overlay_metadata(
    meta: dict[str, Any],
    *,
    document_id: str,
    chunk_index: int,
    total_chunks: int | None = None,
) -> dict[str, Any]:
    """
    Ensure lightweight hierarchy metadata exists for retrieval-time family/adjacency expansion.

    This is intentionally metadata-only: it does not change retrieval ranking/selection behavior.
    """
    if not isinstance(meta, dict):
        return {}

    doc_id = str(document_id or meta.get("document_id") or "").strip()
    idx = max(0, int(chunk_index))
    total = int(total_chunks) if total_chunks is not None else None
    if total is not None and total < 0:
        total = 0

    chunk_key = str(meta.get("chunk_key") or "").strip() or (f"{doc_id}:{idx}" if doc_id else str(idx))
    meta.setdefault("chunk_key", chunk_key)

    node_key = str(meta.get("hierarchy_node_key") or "").strip() or chunk_key
    meta["hierarchy_node_key"] = node_key

    parent_key = _hierarchy_parent_key(meta)
    meta["hierarchy_parent_key"] = parent_key or None
    meta["hierarchy_level"] = _hierarchy_level(meta, parent_key)
    meta["hierarchy_basis"] = _hierarchy_basis(meta)
    meta["hierarchy_family_key"] = _hierarchy_family_key(
        meta,
        document_id=doc_id,
        parent_key=parent_key,
        node_key=node_key,
    )

    if meta.get("hierarchy_sibling_index") is None:
        meta["hierarchy_sibling_index"] = idx

    _set_adjacent_hierarchy_metadata(
        meta,
        direction="prev",
        document_id=doc_id,
        default_index=idx - 1 if idx > 0 else None,
    )
    _set_adjacent_hierarchy_metadata(
        meta,
        direction="next",
        document_id=doc_id,
        default_index=idx + 1 if total is not None and idx + 1 < total else None,
    )

    return meta


__all__ = [
    "ensure_hierarchy_overlay_metadata",
    "infer_chunk_structure",
    "normalize_image_metadata",
    "normalize_section_metadata",
]
