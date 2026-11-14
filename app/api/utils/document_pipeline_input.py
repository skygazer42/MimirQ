"""Validate document pipeline form input and convert it into domain options."""

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.schemas.documents import DocumentPipelineOptions, PipelineOptionOverrides
from app.core.config import settings
from app.core.env import is_production_env
from app.services.pipeline_config import validate_pipeline_execution
from app.types.pipeline import PipelineOptions

CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL = "chunk_overlap must be less than chunk_size"


def _pipeline_validation_error(message: str, error: ValidationError) -> HTTPException:
    if not is_production_env():
        message = f"{message}: {str(error)[:200]}"
    return HTTPException(status_code=400, detail=message)


def parse_pipeline_json(pipeline: str | None) -> DocumentPipelineOptions | None:
    if pipeline is None:
        return None
    max_chars = settings.PIPELINE_FORM_JSON_MAX_CHARS
    if max_chars > 0 and len(pipeline) > max_chars:
        raise HTTPException(status_code=400, detail="pipeline is too large")
    try:
        return DocumentPipelineOptions.model_validate_json(pipeline)
    except ValidationError as exc:
        raise _pipeline_validation_error("Invalid pipeline JSON", exc) from exc


def to_pipeline_options(
    *,
    pipeline: DocumentPipelineOptions | None = None,
    overrides: PipelineOptionOverrides | None = None,
) -> PipelineOptions:
    pipeline_values = {}
    if pipeline is not None:
        pipeline_values.update(pipeline.model_dump(exclude_none=True))

    # Only supplied override fields replace the pipeline; False and zero stay explicit.
    if overrides is not None:
        pipeline_values.update(overrides.model_dump(exclude_none=True))
    try:
        validated_pipeline = DocumentPipelineOptions.model_validate(pipeline_values)
    except ValidationError as exc:
        raise _pipeline_validation_error("Invalid pipeline options", exc) from exc
    options = PipelineOptions(**validated_pipeline.model_dump(exclude_none=True))
    validate_pipeline_execution(options)
    return options


def validate_chunk_params(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=400,
            detail=CHUNK_OVERLAP_LESS_THAN_SIZE_DETAIL,
        )
