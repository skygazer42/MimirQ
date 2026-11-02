import json
from dataclasses import asdict, dataclass, replace
from typing import Any, cast

from fastapi import HTTPException

from app.api.schemas.document import DocumentPipelineOptions
from app.core.config import settings
from app.core.env import is_production_env
from app.types.pipeline import PipelineOptions

CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL = "chunk_overlap must be less than chunk_size"


@dataclass(frozen=True)
class PipelineOptionOverrides:
    governance_enabled: bool | None = None
    governance_remove_toc_lines: bool | None = None
    governance_remove_noise_lines: bool | None = None
    governance_unwrap_lines: bool | None = None
    governance_remove_common_lines: bool | None = None
    governance_unwrap_max_line_length: int | None = None
    governance_noise_min_chars: int | None = None
    governance_noise_ratio_threshold: float | None = None
    governance_common_lines_min_docs: int | None = None
    governance_common_lines_min_ratio: float | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    chunk_vector_enabled: bool | None = None
    bm25_index_enabled: bool | None = None
    kg_enabled: bool | None = None
    event_vector_enabled: bool | None = None
    entity_vector_enabled: bool | None = None


def _parse_pipeline_json(pipeline: str | None) -> DocumentPipelineOptions | None:
    raw = (pipeline or "").strip()
    if not raw or raw.lower() in {"null", "none", "undefined"}:
        return None
    max_len = int(settings.PIPELINE_FORM_JSON_MAX_CHARS or 200_000)
    if max_len > 0 and len(raw) > max_len:
        raise HTTPException(status_code=400, detail="pipeline is too large")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("pipeline must be a JSON object")
        return DocumentPipelineOptions.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        msg = (str(exc) or exc.__class__.__name__)[:200]
        detail = "Invalid pipeline JSON" if is_production_env() else f"Invalid pipeline JSON: {msg}"
        raise HTTPException(status_code=400, detail=detail) from exc


def _validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=400,
            detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL,
        )


def _resolve_pipeline_option_overrides(
    *,
    overrides: PipelineOptionOverrides | None,
    legacy_overrides: dict[str, Any],
) -> PipelineOptionOverrides:
    base = overrides or PipelineOptionOverrides()
    if not legacy_overrides:
        return base
    return cast(PipelineOptionOverrides, replace(base, **legacy_overrides))


def to_pipeline_options(
    *,
    pipeline: DocumentPipelineOptions | None = None,
    overrides: PipelineOptionOverrides | None = None,
    **legacy_overrides: Any,
) -> PipelineOptions:
    resolved_overrides = _resolve_pipeline_option_overrides(
        overrides=overrides,
        legacy_overrides=legacy_overrides,
    )
    overrides_dict = {key: value for key, value in asdict(resolved_overrides).items() if value is not None}

    if pipeline is None:
        pipeline = DocumentPipelineOptions(**overrides_dict) if overrides_dict else None
    elif overrides_dict:
        try:
            merged = pipeline.model_dump()
            merged.update(overrides_dict)
            pipeline = DocumentPipelineOptions(**merged)
        except Exception as exc:  # noqa: BLE001
            message = (str(exc) or exc.__class__.__name__)[:200]
            detail = "Invalid pipeline options" if is_production_env() else f"Invalid pipeline options: {message}"
            raise HTTPException(status_code=400, detail=detail) from exc

    if pipeline is None:
        return PipelineOptions()

    data = pipeline.model_dump(exclude_none=True)
    return PipelineOptions(**data) if data else PipelineOptions()
