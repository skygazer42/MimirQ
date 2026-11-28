"""Small-model manifest and runtime helpers for parsing pipelines."""

from app.rag.ingestion.parsing.models.manifest import (
    SmallModelManifest,
    SmallModelSpec,
    load_default_small_model_manifest,
    load_small_model_manifest,
)
from app.rag.ingestion.parsing.models.runtime import LoadedSmallModel, SmallModelRuntime, SmallModelStatus
from app.rag.ingestion.parsing.models.table_transformer_onnx import predict_table_structure_detections

__all__ = [
    "LoadedSmallModel",
    "SmallModelManifest",
    "SmallModelRuntime",
    "SmallModelSpec",
    "SmallModelStatus",
    "load_default_small_model_manifest",
    "load_small_model_manifest",
    "predict_table_structure_detections",
]
