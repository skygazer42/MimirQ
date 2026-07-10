"""
Evidence drift audit utilities.

Purpose:
- Detect stale EvidenceSuite / regression `reference_sources` that no longer resolve.
- Provide PII-safe drift reasons + rates for reporting and repair workflows.

Notes:
- This module intentionally avoids reading/storing chunk content; it operates on ids + metadata only.
"""


from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.services.dataset_profile_service import (
    directory_bucket_from_source_path,
    extract_language_bucket,
    quality_bucket_from_governance_quality,
)

DRIFT_REASON_DOCUMENT_MISSING = "document_missing"
DRIFT_REASON_DOCUMENT_DATASET_MISMATCH = "document_dataset_mismatch"
DRIFT_REASON_CHUNK_MISSING = "chunk_missing"
DRIFT_REASON_CHUNK_DISABLED = "chunk_disabled"
DRIFT_REASON_CHUNK_DOCUMENT_MISMATCH = "chunk_document_mismatch"
DRIFT_REASON_CHUNK_INDEX_MISMATCH = "chunk_index_mismatch"
DRIFT_REASON_PIPELINE_HASH_MISMATCH = "pipeline_hash_mismatch"
DRIFT_REASON_DOC_PIPELINE_KEY_MISMATCH = "doc_pipeline_key_mismatch"


@dataclass(frozen=True, slots=True)
class DriftSliceKeys:
    file_type: str
    language: str
    quality_bucket: str
    directory: str


def _as_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except Exception:
        return None


def build_drift_slice_keys(*, document_file_type: object, document_metadata: object) -> DriftSliceKeys:
    meta = document_metadata if isinstance(document_metadata, dict) else {}
    file_type = str(document_file_type or "").strip().lower() or "unknown"
    # Align with dataset profile slice taxonomy.
    language = extract_language_bucket(meta)
    quality_bucket = quality_bucket_from_governance_quality(meta.get("governance_quality"))
    directory = directory_bucket_from_source_path(meta.get("source_path"))
    return DriftSliceKeys(
        file_type=file_type or "unknown",
        language=language or "unknown",
        quality_bucket=quality_bucket or "unknown",
        directory=directory or "root",
    )


def classify_reference_source_drift(
    *,
    reference_source: dict[str, Any],
    document_row: dict[str, Any] | None,
    chunk_row: dict[str, Any] | None,
    suite_dataset_id: UUID | None,
) -> tuple[bool, str, dict[str, Any], dict[str, Any]]:
    """
    Classify a single reference source pointer as ok/drift with a primary drift reason.

    Returns:
        (ok, reason, expected, observed)
    """
    expected: dict[str, Any] = {}
    observed: dict[str, Any] = {}

    doc_id = _as_uuid(reference_source.get("document_id"))
    chunk_id = _as_uuid(reference_source.get("chunk_id"))
    expected["document_id"] = str(doc_id) if doc_id else None
    expected["chunk_id"] = str(chunk_id) if chunk_id else None
    expected["chunk_index"] = reference_source.get("chunk_index")
    expected["pipeline_hash"] = reference_source.get("pipeline_hash")
    expected["doc_pipeline_key"] = reference_source.get("doc_pipeline_key")

    if document_row is None:
        return False, DRIFT_REASON_DOCUMENT_MISSING, expected, observed

    doc_dataset_id = _as_uuid(document_row.get("dataset_id"))
    # Evidence suites are dataset-scoped: any document outside the dataset (including legacy NULL) is drift.
    if suite_dataset_id is not None and doc_dataset_id != suite_dataset_id:
        observed["document_dataset_id"] = str(doc_dataset_id) if doc_dataset_id is not None else None
        observed["suite_dataset_id"] = str(suite_dataset_id)
        return False, DRIFT_REASON_DOCUMENT_DATASET_MISMATCH, expected, observed

    if chunk_row is None:
        return False, DRIFT_REASON_CHUNK_MISSING, expected, observed

    # Chunk belongs to document?
    observed_chunk_doc_id = _as_uuid(chunk_row.get("document_id"))
    observed["chunk_document_id"] = str(observed_chunk_doc_id) if observed_chunk_doc_id else None
    if doc_id is not None and observed_chunk_doc_id is not None and observed_chunk_doc_id != doc_id:
        return False, DRIFT_REASON_CHUNK_DOCUMENT_MISMATCH, expected, observed

    # Optional chunk_index match.
    exp_idx = reference_source.get("chunk_index")
    if exp_idx is not None:
        try:
            exp_idx_int = int(exp_idx)
        except Exception:
            exp_idx_int = None
        if exp_idx_int is not None:
            try:
                obs_idx = int(chunk_row.get("chunk_index")) if chunk_row.get("chunk_index") is not None else None
            except Exception:
                obs_idx = None
            observed["chunk_index"] = obs_idx
            if obs_idx != exp_idx_int:
                return False, DRIFT_REASON_CHUNK_INDEX_MISMATCH, expected, observed

    # Optional pipeline hash match.
    exp_pipeline_hash = reference_source.get("pipeline_hash")
    if isinstance(exp_pipeline_hash, str) and exp_pipeline_hash.strip():
        exp_pipeline_hash = exp_pipeline_hash.strip()
        cmeta = chunk_row.get("metadata") if isinstance(chunk_row.get("metadata"), dict) else {}
        obs_pipeline_hash = str(cmeta.get("pipeline_hash") or "").strip()
        observed["pipeline_hash"] = obs_pipeline_hash or None
        if obs_pipeline_hash != exp_pipeline_hash:
            return False, DRIFT_REASON_PIPELINE_HASH_MISMATCH, expected, observed

    # Optional doc_pipeline_key match.
    exp_doc_pipeline_key = reference_source.get("doc_pipeline_key")
    if isinstance(exp_doc_pipeline_key, str) and exp_doc_pipeline_key.strip():
        exp_doc_pipeline_key = exp_doc_pipeline_key.strip()
        cmeta = chunk_row.get("metadata") if isinstance(chunk_row.get("metadata"), dict) else {}
        obs_key = str(cmeta.get("doc_pipeline_key") or "").strip()
        observed["doc_pipeline_key"] = obs_key or None
        if obs_key != exp_doc_pipeline_key:
            return False, DRIFT_REASON_DOC_PIPELINE_KEY_MISMATCH, expected, observed

    # Disabled chunk (best-effort).
    if chunk_row.get("disabled_at") is not None:
        return False, DRIFT_REASON_CHUNK_DISABLED, expected, observed

    return True, "ok", expected, observed


__all__ = [
    "DRIFT_REASON_CHUNK_DISABLED",
    "DRIFT_REASON_CHUNK_DOCUMENT_MISMATCH",
    "DRIFT_REASON_CHUNK_INDEX_MISMATCH",
    "DRIFT_REASON_CHUNK_MISSING",
    "DRIFT_REASON_DOC_PIPELINE_KEY_MISMATCH",
    "DRIFT_REASON_DOCUMENT_DATASET_MISMATCH",
    "DRIFT_REASON_DOCUMENT_MISSING",
    "DRIFT_REASON_PIPELINE_HASH_MISMATCH",
    "DriftSliceKeys",
    "build_drift_slice_keys",
    "classify_reference_source_drift",
]
