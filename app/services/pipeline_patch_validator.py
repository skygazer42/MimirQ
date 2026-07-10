
from typing import Any

from pydantic import ValidationError

from app.api.schemas.document import DocumentPipelineOptions


def normalize_document_pipeline_patch(
    raw: object,
    *,
    field_label: str,
    invalid_message: str | None = None,
    max_keys: int | None = None,
) -> dict[str, Any]:
    """
    Validate a partial DocumentPipelineOptions patch and store explicit values only.

    The validator is shared by ingestion policies, governance profiles, and plugin
    manifests so all platform surfaces use the same public pipeline option shape.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{field_label} must be an object")
    if max_keys is not None and len(raw) > max_keys:
        raise ValueError(f"{field_label} too many keys")

    allowed = set(DocumentPipelineOptions.model_fields.keys())
    unknown = [key for key in raw.keys() if key not in allowed]
    if unknown:
        unknown_sorted = ", ".join(sorted(map(str, unknown))[:20])
        raise ValueError(f"{field_label} contains unknown keys: {unknown_sorted}")

    try:
        validated = DocumentPipelineOptions(**raw)
    except ValidationError as exc:
        raise ValueError(invalid_message or f"invalid {field_label}") from exc

    return validated.model_dump(exclude_none=True)


__all__ = ["normalize_document_pipeline_patch"]
