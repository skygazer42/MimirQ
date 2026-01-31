"""
Metadata normalization utilities.

Goals:
- Normalize metadata across different parser/chunker outputs for compatibility
- Avoid scattered business logic with "patch-style handling" across multiple modules
"""


from typing import Any, Dict


def normalize_image_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
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

    return meta


def normalize_section_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
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


__all__ = ["normalize_image_metadata", "normalize_section_metadata"]

