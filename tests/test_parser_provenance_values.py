from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.ingestion import pipeline as flow
from app.rag.ingestion.indexing.support import stages
from app.rag.ingestion.indexing.support.recovery import upsert_ingest_checkpoint
from app.rag.ingestion.parsing.errors import ParsingInternalError
from app.rag.ingestion.parsing.factory import ParserFactory
from app.rag.ingestion.parsing.processors.parse_cache import build_parse_cache_key as local_key
from app.services.parsing.cache import SCHEMA, ParseCacheEntry
from app.services.parsing.cache import build_parse_cache_key as remote_key


def test_parse_cache_formats_do_not_reuse_old_inferred_provenance() -> None:
    assert (
        remote_key(file_sha256="sha", resolved_backend="auto", config_hash="config", version="v1")
        != "834d29417cc1532e9a654b8048ef485e"
    )
    assert (
        local_key(file_sha256="sha", parser_backend="auto", config_hash="config")
        != "0a84e67241a52fe728cdb43e023d216a0a3d1ff1f9a8b8cd0e62733ed6b57f49"
    )
    old = {
        "schema": "mimirq.parse_cache.v1",
        "created_at": "2026-11-08T00:00:00+00:00",
        "file_sha256": "sha",
        "resolved_backend": "auto",
        "config_hash": "config",
        "documents": [],
    }
    assert ParseCacheEntry.from_obj(old) is None


@pytest.mark.parametrize("backend", [None, "", 0, False])
def test_remote_parse_cache_requires_actual_backend_provenance(backend) -> None:
    payload = {
        "schema": SCHEMA,
        "created_at": "2026-11-08T00:00:00+00:00",
        "file_sha256": "sha",
        "config_hash": "config",
        "resolved_backend": backend,
        "documents": [{"page_content": "cached", "metadata": {}}],
    }
    assert ParseCacheEntry.from_obj(payload) is None


@pytest.mark.asyncio
async def test_remote_cache_hit_reports_the_backend_that_produced_the_content(monkeypatch) -> None:
    monkeypatch.setattr(stages.settings, "PARSE_CACHE_ENABLED", True)
    monkeypatch.setattr(stages.settings, "MINIO_ENABLED", True)
    entry = ParseCacheEntry(
        "2026-11-08T00:00:00+00:00",
        "sha",
        "pandoc",
        "config",
        [{"page_content": "cached", "metadata": {}, "id": "chunk"}],
    )
    monkeypatch.setattr(stages, "get_parse_cache", lambda **_kwargs: (entry, 1))
    recorded = []
    monkeypatch.setattr(stages, "_record_processing_metadata", lambda *_args, **kwargs: recorded.append(kwargs))
    monkeypatch.setattr(stages, "_persist_parse_provenance", lambda *_args: None)
    monkeypatch.setattr(stages, "_persist_parse_quality", lambda **_kwargs: None)
    document_id = uuid4()
    result = await stages.parse_document(
        db=SimpleNamespace(commit=lambda: None, refresh=lambda _document: None),
        db_document=SimpleNamespace(
            id=document_id, doc_metadata={"file_sha256": "sha", "pipeline_hash": "config"}, filename="cached.docx"
        ),
        file_path=Path("cached.docx"),
        document_id=document_id,
        tenant_id=uuid4(),
        dataset_id="dataset",
        parser_backend="auto",
        chunk_strategy="separator",
        artifact_dirs=set(),
    )
    assert result.resolved_backend == "pandoc"
    assert recorded[0]["parser_backend"] == "pandoc"


@pytest.mark.asyncio
async def test_live_parser_response_cannot_omit_its_resolved_backend(monkeypatch) -> None:
    monkeypatch.setattr(stages, "_artifact_root", lambda **_kwargs: Path("unused"))

    async def incomplete_job(**_kwargs):
        return {"documents": []}

    monkeypatch.setattr(stages, "_run_parser_job", incomplete_job)
    with pytest.raises(ParsingInternalError, match="Parser returned malformed documents") as error:
        await stages._parse_documents(
            db=object(),
            file_path=Path("document.docx"),
            document_id=uuid4(),
            tenant_id=uuid4(),
            dataset_id="dataset",
            effective_parser_backend=None,
            pdf_quality=None,
            html_xpath=None,
            artifact_dirs=set(),
        )
    assert isinstance(error.value.__cause__, KeyError)


@pytest.mark.asyncio
async def test_legacy_indexed_checkpoint_without_provenance_is_not_reused(monkeypatch) -> None:
    metadata = upsert_ingest_checkpoint(
        {"pipeline_hash": "config", "file_sha256": "sha"}, stage="indexed", source="test"
    )

    def unexpected_query(*_args):
        pytest.fail("A checkpoint without parser provenance cannot start index finalization")

    monkeypatch.setattr(flow, "_require_primary_index_channels_ready", lambda *_args, **_kwargs: "config")
    result = await flow._resume_from_indexed_checkpoint(
        db=SimpleNamespace(query=unexpected_query),
        db_document=SimpleNamespace(doc_metadata=metadata),
        tenant_id=uuid4(),
        document_id=uuid4(),
        prepared_state=SimpleNamespace(pipeline_effective=SimpleNamespace()),
        with_stage_durations=lambda value: value,
    )
    assert result is None


@pytest.mark.parametrize("value", [None, "", 0, False, " Requested "])
def test_parser_telemetry_keeps_requested_values_without_inventing_execution(value) -> None:
    attributes = flow._parse_stage_otel_attributes(
        db_document=SimpleNamespace(
            doc_metadata={"parser_backend_requested": value, "chunk_strategy_requested": value}
        ),
        file_path=Path("document.pdf"),
        parser_backend="fallback",
        chunk_strategy="fallback",
    )
    if value is None:
        assert "parser.backend_requested" not in attributes
        assert "chunk.strategy_requested" not in attributes
    else:
        assert attributes["parser.backend_requested"] == value
        assert attributes["chunk.strategy_requested"] == value


@pytest.mark.parametrize("backend", [0, False, [], {}])
def test_parser_factory_exposes_wrong_selector_types(backend) -> None:
    with pytest.raises(AttributeError):
        ParserFactory().resolve_backend(".txt", backend)
