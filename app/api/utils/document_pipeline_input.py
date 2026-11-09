"""Validate document pipeline form input and convert it into domain options."""

import json
from dataclasses import asdict

from fastapi import HTTPException

from app.api.schemas.document import DocumentPipelineOptions
from app.api.schemas.document_ingestion import PipelineOptionOverrides
from app.core.config import settings
from app.core.env import is_production_env
from app.types.pipeline import PipelineOptions

CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL = "chunk_overlap must be less than chunk_size"


def parse_pipeline_json(pipeline: str | None) -> DocumentPipelineOptions | None:
    raw = (pipeline or "").strip()
    if not raw or raw.lower() in {"null", "none", "undefined"}:
        return None
    max_len = settings.PIPELINE_FORM_JSON_MAX_CHARS or 200_000
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


def to_pipeline_options(
    *,
    pipeline: DocumentPipelineOptions | None = None,
    overrides: PipelineOptionOverrides | None = None,
) -> PipelineOptions:
    resolved_overrides = overrides or PipelineOptionOverrides()
    overrides_dict = {k: v for k, v in asdict(resolved_overrides).items() if v is not None}

    if pipeline is None:
        pipeline = DocumentPipelineOptions(**overrides_dict) if overrides_dict else None
    elif overrides_dict:
        try:
            merged = pipeline.model_dump()
            merged.update(overrides_dict)
            pipeline = DocumentPipelineOptions(**merged)
        except Exception as exc:  # noqa: BLE001
            msg = (str(exc) or exc.__class__.__name__)[:200]
            detail = "Invalid pipeline options" if is_production_env() else f"Invalid pipeline options: {msg}"
            raise HTTPException(status_code=400, detail=detail) from exc

    if pipeline is None:
        return PipelineOptions()

    from app.services.pipeline_config import validate_pipeline_execution

    data = pipeline.model_dump(exclude_none=True)
    options = PipelineOptions(**data) if data else PipelineOptions()
    validate_pipeline_execution(options)
    return options


def validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=400,
            detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL,
        )
