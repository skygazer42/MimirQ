import pytest

from app.services.document_identity import sync_pipeline_execution_identity
from app.services.pipeline_provenance_service import build_pipeline_version_snapshot


@pytest.mark.parametrize(
    "field", ["parser_backend", "parser_backend_requested", "chunk_strategy", "chunk_strategy_requested"]
)
def test_execution_identity_preserves_empty_metadata_fields(field: str) -> None:
    metadata = {field: ""}

    identity = sync_pipeline_execution_identity(metadata, content_sha256="abc", pipeline_hash="pipeline-1")

    assert identity[field] == ""
    assert metadata["pipeline_execution_identity"][field] == ""
    assert identity["dedup_key"] == "abc:pipeline-1"


def test_execution_identity_keeps_an_explicit_empty_resolved_backend() -> None:
    metadata = {"parser_backend_resolved": "basic"}

    identity = sync_pipeline_execution_identity(
        metadata, content_sha256="abc", pipeline_hash="pipeline-1", parser_backend_resolved=""
    )

    assert identity["parser_backend_resolved"] == ""
    assert metadata["parser_backend_resolved"] == "basic"


@pytest.mark.parametrize("pipeline_hash", ["", None])
def test_execution_identity_preserves_unavailable_pipeline_identity(pipeline_hash: str | None) -> None:
    metadata = {"pipeline_execution_id": "old-id"}

    identity = sync_pipeline_execution_identity(metadata, content_sha256="abc", pipeline_hash=pipeline_hash)

    assert identity["pipeline_hash"] == pipeline_hash
    assert identity["dedup_key"] is None
    assert "pipeline_execution_id" not in metadata


@pytest.mark.parametrize(
    "field,transform",
    [
        ("parser_backend", "parse"),
        ("parser_backend_requested", "parse"),
        ("file_type", "parse"),
        ("chunk_strategy", "chunk"),
        ("chunk_strategy_requested", "chunk"),
        ("governance_version", "governance"),
    ],
)
def test_provenance_hash_distinguishes_empty_and_missing_configuration(field: str, transform: str) -> None:
    parameters = {
        "pipeline_hash": "pipeline-1",
        "created_at": "2026-11-07T00:00:00+00:00",
        "build_sha": "build-1",
        "embedding_space_hash": "space-1",
    }

    empty = build_pipeline_version_snapshot(meta={field: ""}, **parameters)
    missing = build_pipeline_version_snapshot(meta={}, **parameters)

    assert empty["transforms"][transform]["hash"] != missing["transforms"][transform]["hash"]
    assert empty["pipeline_run_hash"] != missing["pipeline_run_hash"]


def test_provenance_preserves_an_explicit_empty_embedding_space() -> None:
    snapshot = build_pipeline_version_snapshot(meta={}, pipeline_hash="pipeline-1", embedding_space_hash="")

    assert snapshot["embedding_space_hash"] == ""
    assert snapshot["transforms"]["index"]["embedding_space_hash"] == ""
