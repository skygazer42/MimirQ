import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document as LCDocument
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace.status import StatusCode


class _CollectingExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans = []

    def export(self, spans):  # noqa: ANN001
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


class _StageQuery:
    def __init__(self, result) -> None:  # noqa: ANN001
        self._result = result

    def populate_existing(self):  # noqa: ANN201
        return self

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):  # noqa: ANN201
        return self._result

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def all(self):  # noqa: ANN201
        return []


class _StageDB:
    def __init__(self, db_document) -> None:  # noqa: ANN001
        self._db_document = db_document

    def query(self, _model):  # noqa: ANN001, ANN201
        return _StageQuery(self._db_document)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def add(self, _obj) -> None:  # noqa: ANN001
        return None

    def flush(self) -> None:
        return None


class _Cfg(SimpleNamespace):
    def __getattr__(self, name: str):  # noqa: ANN204
        if name.endswith("_params"):
            return {}
        if name.endswith("_rule_packs"):
            return []
        if name.endswith("_plugin"):
            return ""
        if name.endswith("_mode"):
            return "mask"
        if name.endswith("_mask"):
            return "***"
        if name.endswith("_enabled"):
            return False
        if name.endswith("_xpath"):
            return None
        return 0


class _FakeParsingStage:
    def __init__(self, _service) -> None:  # noqa: ANN001
        return None

    async def run(self, **_kwargs):  # noqa: ANN003, ANN202
        return SimpleNamespace(
            resolved_backend="basic",
            resolved_chunk_strategy="langchain_recursive",
            documents=[LCDocument(page_content="hello world", metadata={"page": 1})],
            chunks=None,
        )


class _FakeNormalizeStage:
    def run(self, *, items):  # noqa: ANN201
        return list(items)


class _FakeGovernanceStage:
    def run(self, *, items, enabled, kwargs):  # noqa: ANN001, ANN201
        return SimpleNamespace(items=list(items), stats={"enabled": bool(enabled), "kwargs": bool(kwargs)})


class _FakeChunkingStage:
    def run(self, **_kwargs):  # noqa: ANN003, ANN201
        return SimpleNamespace(chunks=[LCDocument(page_content="chunk body", metadata={"page": 1})])


class _FakeChunkDedupStage:
    def run(self, *, chunks, enabled):  # noqa: ANN201
        return SimpleNamespace(chunks=list(chunks), duplicates_dropped=0)


class _FakeChunkAssetStage:
    def __init__(self, _service) -> None:  # noqa: ANN001
        return None

    def run(self, *, chunks, **_kwargs):  # noqa: ANN003, ANN201
        return SimpleNamespace(chunks=list(chunks), img_ids=set())


class _FakeIndexStage:
    def run(self, **_kwargs):  # noqa: ANN003, ANN201
        return SimpleNamespace(
            chunk_ids=[uuid.uuid4()],
            total_characters=10,
            db_chunks=[SimpleNamespace(id=uuid.uuid4())],
        )


def _build_ingest_span_document(*, document_id: uuid.UUID, tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        filename="span-test.txt",
        file_type="txt",
        status="pending",
        doc_metadata={
            "pipeline_hash": "pipe-1",
            "file_sha256": "sha-1",
            "parser_backend": "basic",
            "chunk_strategy": "langchain_recursive",
        },
    )


def _build_pipeline_effective() -> _Cfg:
    return _Cfg(
        governance_enabled=True,
        chunk_size=256,
        chunk_overlap=32,
        chunk_strategy_params={},
        chunk_python_plugin="",
        chunk_python_params={},
        parse_fallback_enabled=False,
        persist_parsed_content=False,
        image_caption_enabled=False,
        image_ocr_enabled=False,
        image_ocr_max_chars=0,
        image_ocr_max_images=0,
        governance_pii_anonymize=False,
        governance_pii_mode="mask",
        governance_pii_mask="[REDACTED]",
        governance_secrets_redact=False,
        governance_secrets_mode="mask",
        governance_secrets_mask="***",
        near_dedup_enabled=False,
        kg_enabled=True,
        governance_html_xpath=None,
    )


def test_metrics_span_records_otel_exception_status_and_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import metrics_logger

    exporter = _CollectingExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test.ingest")
    logged: list[dict[str, object]] = []

    monkeypatch.setattr(metrics_logger, "_get_optional_otel_tracer", lambda: tracer, raising=True)
    monkeypatch.setattr(metrics_logger, "log_metrics", lambda payload: logged.append(dict(payload)), raising=True)

    with pytest.raises(RuntimeError, match="boom"):
        with metrics_logger.metrics_span(
            "ingest.test",
            otel_span_name="ingest.parse",
            otel_attributes={
                "ingest.stage": "parse",
                "document.file_type": "txt",
                "parser.backend_requested": "basic",
            },
            parser_backend_requested="basic",
        ):
            raise RuntimeError("boom")

    assert logged and logged[0]["event"] == "ingest.test"
    assert logged[0]["success"] is False
    assert logged[0]["error"] == "boom"
    assert len(exporter.spans) == 1
    span = exporter.spans[0]
    assert span.name == "ingest.parse"
    assert span.attributes["ingest.stage"] == "parse"
    assert span.attributes["document.file_type"] == "txt"
    assert span.attributes["parser.backend_requested"] == "basic"
    assert span.status.status_code is StatusCode.ERROR
    assert any(event.name == "exception" for event in span.events)


def test_metrics_span_skips_otel_when_provider_is_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import metrics_logger

    logged: list[dict[str, object]] = []

    class _ProxyProvider:
        pass

    class _FakeTraceModule:
        @staticmethod
        def get_tracer_provider():  # noqa: ANN201
            return _ProxyProvider()

    monkeypatch.setattr(
        metrics_logger,
        "_resolve_otel_api",
        lambda: (_FakeTraceModule(), object, SimpleNamespace(OK="ok", ERROR="error")),
        raising=True,
    )
    monkeypatch.setattr(metrics_logger, "log_metrics", lambda payload: logged.append(dict(payload)), raising=True)

    with pytest.raises(RuntimeError, match="no exporter"):
        with metrics_logger.metrics_span(
            "ingest.test",
            otel_span_name="ingest.finalize",
            otel_attributes={"ingest.stage": "finalize"},
        ):
            raise RuntimeError("no exporter")

    assert logged and logged[0]["success"] is False
    assert logged[0]["error"] == "no exporter"


@pytest.mark.asyncio
async def test_process_document_wires_five_ingest_stage_spans(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from app.parsing.processors import processor

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    file_path = tmp_path / "span-test.txt"
    file_path.write_text("span coverage", encoding="utf-8")
    db_document = _build_ingest_span_document(document_id=document_id, tenant_id=tenant_id)
    service = processor.DocumentProcessorService()
    span_calls: list[dict[str, object]] = []

    @contextmanager
    def _capture_metrics_span(event: str, *, otel_span_name: str | None = None, otel_attributes=None, **fields):  # noqa: ANN001
        span_calls.append(
            {
                "event": event,
                "otel_span_name": otel_span_name,
                "otel_attributes": dict(otel_attributes or {}),
                "fields": dict(fields),
            }
        )
        yield

    async def _cancel_check(*, force: bool = False) -> bool:  # noqa: ARG001
        return False

    async def _update_status(*_args, **_kwargs) -> None:  # noqa: ANN003, ANN202
        return None

    async def _run_post_completion_kg(**_kwargs) -> None:  # noqa: ANN003, ANN202
        return None

    monkeypatch.setattr(processor, "metrics_span", _capture_metrics_span, raising=True)
    monkeypatch.setattr(processor, "log_metrics", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(processor, "ParsingStage", _FakeParsingStage, raising=True)
    monkeypatch.setattr(processor, "NormalizeStage", _FakeNormalizeStage, raising=True)
    monkeypatch.setattr(processor, "GovernanceStage", _FakeGovernanceStage, raising=True)
    monkeypatch.setattr(processor, "ChunkingStage", _FakeChunkingStage, raising=True)
    monkeypatch.setattr(processor, "ChunkDedupStage", _FakeChunkDedupStage, raising=True)
    monkeypatch.setattr(processor, "ChunkAssetStage", _FakeChunkAssetStage, raising=True)
    monkeypatch.setattr(processor, "IndexStage", _FakeIndexStage, raising=True)
    monkeypatch.setattr(service, "_build_cancel_check", lambda **_kwargs: _cancel_check, raising=True)
    monkeypatch.setattr(service, "_apply_pending_retry_cleanup", lambda *_args, **_kwargs: "applied", raising=True)
    monkeypatch.setattr(service, "_update_status", _update_status, raising=True)
    monkeypatch.setattr(service, "_record_pipeline_effective", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(service, "_record_document_image_ids", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(service, "_cleanup_parser_artifacts", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(service, "_record_governance_enrichment_metadata", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(service, "_strip_doc_enrichment_fields", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(service, "_record_chunk_postprocess_metadata", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(service, "_record_governance_metadata", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(service, "_record_chunking_stats_metadata", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(service, "_import_parsed_markdown_tables_to_store", lambda *_args, **_kwargs: -1, raising=True)
    monkeypatch.setattr(
        service,
        "_apply_table_sidecar_exclusive_routing",
        lambda *, chunks, **_kwargs: (list(chunks), None),
        raising=True,
    )
    monkeypatch.setattr(
        processor,
        "resolve_pipeline_effective",
        lambda **_kwargs: _build_pipeline_effective(),
        raising=True,
    )
    monkeypatch.setattr(
        processor,
        "build_indexing_options",
        lambda _cfg: SimpleNamespace(chunk_vector_enabled=True, bm25_index_enabled=True),
        raising=True,
    )
    monkeypatch.setattr(processor, "maybe_enrich_document_questions", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(processor, "run_post_completion_kg", _run_post_completion_kg, raising=True)
    monkeypatch.setattr(processor.settings, "CHUNK_MIN_CHARS", 0, raising=False)
    monkeypatch.setattr(processor.settings, "CHUNK_DEDUP_ENABLED", False, raising=False)
    monkeypatch.setattr(processor.settings, "MAX_CHUNKS_PER_DOCUMENT", 0, raising=False)

    result = await service.process_document(
        file_path=file_path,
        document_id=document_id,
        tenant_id=tenant_id,
        db=_StageDB(db_document),
    )

    assert result["status"] == "success"
    stage_spans = [
        call
        for call in span_calls
        if call["otel_span_name"]
        in {
            "ingest.parse",
            "ingest.governance",
            "ingest.chunk",
            "ingest.index",
            "ingest.finalize",
        }
    ]
    assert [call["otel_span_name"] for call in stage_spans] == [
        "ingest.parse",
        "ingest.governance",
        "ingest.chunk",
        "ingest.index",
        "ingest.finalize",
    ]
    assert stage_spans[0]["otel_attributes"] == {
        "ingest.stage": "parse",
        "document.file_type": "txt",
        "parser.backend_requested": "basic",
        "chunk.strategy_requested": "langchain_recursive",
    }
    assert stage_spans[1]["otel_attributes"] == {
        "ingest.stage": "governance",
        "document.file_type": "txt",
        "governance.enabled": True,
    }
    assert stage_spans[2]["otel_attributes"] == {
        "ingest.stage": "chunk",
        "document.file_type": "txt",
        "chunk.strategy": "langchain_recursive",
    }
    assert stage_spans[3]["otel_attributes"] == {
        "ingest.stage": "index",
        "document.file_type": "txt",
        "index.chunk_vector_enabled": True,
        "index.bm25_index_enabled": True,
    }
    assert stage_spans[4]["otel_attributes"] == {
        "ingest.stage": "finalize",
        "document.file_type": "txt",
        "pipeline.kg_enabled": True,
    }
    for call in stage_spans:
        assert "document_id" not in call["otel_attributes"]
        assert "tenant_id" not in call["otel_attributes"]
