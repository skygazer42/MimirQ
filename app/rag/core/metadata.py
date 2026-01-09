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


__all__ = ["normalize_image_metadata"]


