from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.services.evidence_drift_audit import (
    DRIFT_REASON_CHUNK_DISABLED,
    DRIFT_REASON_CHUNK_DOCUMENT_MISMATCH,
    DRIFT_REASON_CHUNK_INDEX_MISMATCH,
    DRIFT_REASON_CHUNK_MISSING,
    DRIFT_REASON_DOC_PIPELINE_KEY_MISMATCH,
    DRIFT_REASON_DOCUMENT_DATASET_MISMATCH,
    DRIFT_REASON_DOCUMENT_MISSING,
    DRIFT_REASON_PIPELINE_HASH_MISMATCH,
    classify_reference_source_drift,
)


def _doc(*, dataset_id=None, file_type="pdf", meta=None):  # noqa: ANN001
    return {"dataset_id": dataset_id, "file_type": file_type, "metadata": meta or {}}


def _chunk(*, document_id=None, chunk_index=0, meta=None, disabled_at=None):  # noqa: ANN001
    return {
        "document_id": document_id,
        "chunk_index": chunk_index,
        "metadata": meta or {},
        "disabled_at": disabled_at,
    }


def test_reference_source_drift_document_missing():  # noqa: D401
    """Missing document should be classified first (even if chunk is also missing)."""
    ref = {"document_id": str(uuid4()), "chunk_id": str(uuid4())}
    ok, reason, _exp, _obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=None,
        chunk_row=None,
        suite_dataset_id=None,
    )
    assert ok is False
    assert reason == DRIFT_REASON_DOCUMENT_MISSING


def test_reference_source_drift_document_dataset_mismatch():  # noqa: D401
    """Document outside suite dataset should be reported as dataset mismatch."""
    suite_ds = uuid4()
    other_ds = uuid4()
    doc_id = uuid4()
    chunk_id = uuid4()
    ref = {"document_id": str(doc_id), "chunk_id": str(chunk_id)}
    ok, reason, _exp, obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=_doc(dataset_id=other_ds),
        chunk_row=_chunk(document_id=doc_id),
        suite_dataset_id=suite_ds,
    )
    assert ok is False
    assert reason == DRIFT_REASON_DOCUMENT_DATASET_MISMATCH
    assert obs.get("suite_dataset_id") == str(suite_ds)
    assert obs.get("document_dataset_id") == str(other_ds)


def test_reference_source_drift_chunk_missing():  # noqa: D401
    """Missing chunk should be classified after document existence checks."""
    doc_id = uuid4()
    ref = {"document_id": str(doc_id), "chunk_id": str(uuid4())}
    ok, reason, _exp, _obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=_doc(dataset_id=None),
        chunk_row=None,
        suite_dataset_id=None,
    )
    assert ok is False
    assert reason == DRIFT_REASON_CHUNK_MISSING


def test_reference_source_drift_chunk_document_mismatch():  # noqa: D401
    """Chunk pointing to a different document id should be classified as document mismatch."""
    doc_id = uuid4()
    other_doc = uuid4()
    ref = {"document_id": str(doc_id), "chunk_id": str(uuid4())}
    ok, reason, _exp, obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=_doc(dataset_id=None),
        chunk_row=_chunk(document_id=other_doc),
        suite_dataset_id=None,
    )
    assert ok is False
    assert reason == DRIFT_REASON_CHUNK_DOCUMENT_MISMATCH
    assert obs.get("chunk_document_id") == str(other_doc)


def test_reference_source_drift_chunk_index_mismatch():  # noqa: D401
    """chunk_index mismatch should be detected when provided."""
    doc_id = uuid4()
    ref = {"document_id": str(doc_id), "chunk_id": str(uuid4()), "chunk_index": 3}
    ok, reason, _exp, obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=_doc(dataset_id=None),
        chunk_row=_chunk(document_id=doc_id, chunk_index=4),
        suite_dataset_id=None,
    )
    assert ok is False
    assert reason == DRIFT_REASON_CHUNK_INDEX_MISMATCH
    assert obs.get("chunk_index") == 4


def test_reference_source_drift_pipeline_hash_mismatch():  # noqa: D401
    """pipeline_hash mismatch should be detected when the reference provides pipeline_hash."""
    doc_id = uuid4()
    ref = {"document_id": str(doc_id), "chunk_id": str(uuid4()), "pipeline_hash": "aaa"}
    ok, reason, _exp, obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=_doc(dataset_id=None),
        chunk_row=_chunk(document_id=doc_id, meta={"pipeline_hash": "bbb"}),
        suite_dataset_id=None,
    )
    assert ok is False
    assert reason == DRIFT_REASON_PIPELINE_HASH_MISMATCH
    assert obs.get("pipeline_hash") == "bbb"


def test_reference_source_drift_doc_pipeline_key_mismatch():  # noqa: D401
    """doc_pipeline_key mismatch should be detected when provided."""
    doc_id = uuid4()
    ref = {"document_id": str(doc_id), "chunk_id": str(uuid4()), "doc_pipeline_key": f"{doc_id}:old"}
    ok, reason, _exp, obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=_doc(dataset_id=None),
        chunk_row=_chunk(document_id=doc_id, meta={"doc_pipeline_key": f"{doc_id}:new"}),
        suite_dataset_id=None,
    )
    assert ok is False
    assert reason == DRIFT_REASON_DOC_PIPELINE_KEY_MISMATCH
    assert obs.get("doc_pipeline_key") == f"{doc_id}:new"


def test_reference_source_drift_chunk_disabled_has_last_priority():  # noqa: D401
    """Disabled chunk is only reported when other checks pass (exists + matches)."""
    doc_id = uuid4()
    ref = {"document_id": str(doc_id), "chunk_id": str(uuid4())}
    ok, reason, _exp, _obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=_doc(dataset_id=None),
        chunk_row=_chunk(document_id=doc_id, disabled_at=datetime.now(UTC)),
        suite_dataset_id=None,
    )
    assert ok is False
    assert reason == DRIFT_REASON_CHUNK_DISABLED


def test_reference_source_ok():  # noqa: D401
    """A matching reference should be classified as ok."""
    doc_id = uuid4()
    ref = {
        "document_id": str(doc_id),
        "chunk_id": str(uuid4()),
        "chunk_index": 0,
        "pipeline_hash": "ph",
        "doc_pipeline_key": f"{doc_id}:ph",
    }
    ok, reason, _exp, _obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=_doc(dataset_id=None),
        chunk_row=_chunk(document_id=doc_id, chunk_index=0, meta={"pipeline_hash": "ph", "doc_pipeline_key": f"{doc_id}:ph"}),
        suite_dataset_id=None,
    )
    assert ok is True
    assert reason == "ok"


def test_reference_source_chunk_index_non_int_is_ignored():  # noqa: D401
    """Non-int chunk_index should not crash classification and should be ignored."""
    doc_id = uuid4()
    ref = {"document_id": str(doc_id), "chunk_id": str(uuid4()), "chunk_index": "x"}
    ok, reason, _exp, _obs = classify_reference_source_drift(
        reference_source=ref,
        document_row=_doc(dataset_id=None),
        chunk_row=_chunk(document_id=doc_id, chunk_index=0),
        suite_dataset_id=None,
    )
    assert ok is True
    assert reason == "ok"
