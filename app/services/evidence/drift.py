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

from app.services.datasets.profile import (
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


def parse_reference_uuid(value: object) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except ValueError:
        return None


def build_drift_slice_keys(*, document_file_type: object, document_metadata: object) -> DriftSliceKeys:
    meta = document_metadata if isinstance(document_metadata, dict) else {}
    file_type = "unknown" if document_file_type is None else str(document_file_type).strip().lower() or "unknown"
    # Align with dataset profile slice taxonomy.
    language = extract_language_bucket(meta)
    quality_bucket = quality_bucket_from_governance_quality(meta.get("governance_quality"))
    directory = directory_bucket_from_source_path(meta.get("source_path"))
    return DriftSliceKeys(
        file_type=file_type,
        language=language,
        quality_bucket=quality_bucket,
        directory=directory,
    )


def _expected_reference_source(reference_source: dict[str, Any]) -> tuple[dict[str, Any], UUID | None]:
    doc_id = parse_reference_uuid(reference_source.get("document_id"))
    chunk_id = parse_reference_uuid(reference_source.get("chunk_id"))
    expected = {
        "document_id": str(doc_id) if doc_id else None,
        "chunk_id": str(chunk_id) if chunk_id else None,
        "chunk_index": reference_source.get("chunk_index"),
        "pipeline_hash": reference_source.get("pipeline_hash"),
        "doc_pipeline_key": reference_source.get("doc_pipeline_key"),
    }
    return expected, doc_id


def _chunk_index_drift(
    *,
    reference_source: dict[str, Any],
    chunk_row: dict[str, Any],
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> tuple[bool, str, dict[str, Any], dict[str, Any]] | None:
    exp_idx = reference_source.get("chunk_index")
    if exp_idx is None:
        return None

    try:
        exp_idx_int = int(exp_idx)
    except (TypeError, ValueError, OverflowError):
        return None

    raw_observed_index = chunk_row.get("chunk_index")
    try:
        obs_idx = int(raw_observed_index) if raw_observed_index is not None else None
    except (TypeError, ValueError, OverflowError):
        obs_idx = None

    observed["chunk_index"] = obs_idx
    if obs_idx != exp_idx_int:
        return False, DRIFT_REASON_CHUNK_INDEX_MISMATCH, expected, observed
    return None


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
    observed: dict[str, Any] = {}
    expected, doc_id = _expected_reference_source(reference_source)

    if document_row is None:
        return False, DRIFT_REASON_DOCUMENT_MISSING, expected, observed

    doc_dataset_id = parse_reference_uuid(document_row.get("dataset_id"))
    # Evidence suites are dataset-scoped: any document outside the dataset (including legacy NULL) is drift.
    if suite_dataset_id is not None and doc_dataset_id != suite_dataset_id:
        observed["document_dataset_id"] = str(doc_dataset_id) if doc_dataset_id is not None else None
        observed["suite_dataset_id"] = str(suite_dataset_id)
        return False, DRIFT_REASON_DOCUMENT_DATASET_MISMATCH, expected, observed

    if chunk_row is None:
        return False, DRIFT_REASON_CHUNK_MISSING, expected, observed

    # Chunk belongs to document?
    observed_chunk_doc_id = parse_reference_uuid(chunk_row.get("document_id"))
    observed["chunk_document_id"] = str(observed_chunk_doc_id) if observed_chunk_doc_id else None
    if doc_id is not None and observed_chunk_doc_id is not None and observed_chunk_doc_id != doc_id:
        return False, DRIFT_REASON_CHUNK_DOCUMENT_MISMATCH, expected, observed

    drift = _chunk_index_drift(
        reference_source=reference_source, chunk_row=chunk_row, expected=expected, observed=observed
    )
    if drift is not None:
        return drift

    raw_metadata = chunk_row.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    for key, reason in (
        ("pipeline_hash", DRIFT_REASON_PIPELINE_HASH_MISMATCH),
        ("doc_pipeline_key", DRIFT_REASON_DOC_PIPELINE_KEY_MISMATCH),
    ):
        expected_value = expected[key]
        if not isinstance(expected_value, str) or not expected_value.strip():
            continue
        actual = metadata.get(key)
        observed[key] = actual
        comparable = actual.strip() if isinstance(actual, str) else actual
        if comparable != expected_value.strip():
            return False, reason, expected, observed

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
    "parse_reference_uuid",
]
