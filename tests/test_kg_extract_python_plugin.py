from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import ValidationError

LEGACY_IMPORT_KG_REF = "tests.fixtures.python_pipeline_import_plugin:build_kg_events"


class _Session:
    def commit(self):  # noqa: D401
        """No-op."""

    def rollback(self):  # noqa: D401
        """No-op."""

    def close(self):  # noqa: D401
        """No-op."""


class _Chunk:
    def __init__(self, *, tenant_id: UUID, document_id: UUID, chunk_id: UUID):
        self.id = chunk_id
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.chunk_index = 7
        self.page_number = None
        self.start_char = 10
        self.end_char = 30
        self.content = "Record name: account renewal\nRequired material: identity proof"
        self.doc_metadata = {
            "source_record_id": "record-1",
            "chunk_kind": "demo_case_full",
            "pipeline_hash": "ph-plugin",
        }


def test_extract_config_rejects_nested_kg_python_params() -> None:
    from app.rag.kg.extraction.config import ExtractConfig

    with pytest.raises(ValidationError, match="kg_python_params values must be JSON primitives"):
        ExtractConfig(kg_python_params={"business_profile": {"mode": "nested"}})


def test_extract_config_rejects_file_path_kg_python_plugin() -> None:
    from app.rag.kg.extraction.config import ExtractConfig

    with pytest.raises(ValidationError, match="kg_python_plugin must be an import path or registered KG plugin ref"):
        ExtractConfig(kg_python_plugin="../plugins/demo.py")


def test_extract_config_rejects_import_path_kg_python_plugin_by_default() -> None:
    from app.rag.kg.extraction.config import ExtractConfig

    with pytest.raises(ValidationError, match="kg_python_plugin import refs are disabled"):
        ExtractConfig(kg_python_plugin=LEGACY_IMPORT_KG_REF)


def test_extract_config_allows_import_path_kg_python_plugin_when_prefix_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.kg.extraction.config import ExtractConfig

    monkeypatch.setattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "tests.fixtures.", raising=False)

    cfg = ExtractConfig(kg_python_plugin=LEGACY_IMPORT_KG_REF)

    assert cfg.kg_python_plugin == LEGACY_IMPORT_KG_REF


def test_extract_config_rejects_non_kg_registered_plugin_ref() -> None:
    from app.rag.kg.extraction.config import ExtractConfig

    with pytest.raises(ValidationError, match="kg_python_plugin registered ref must target the kg stage"):
        ExtractConfig(kg_python_plugin="plugin:demo@1.0.0:chunk")


def test_extract_config_accepts_registered_kg_plugin_ref() -> None:
    from app.rag.kg.extraction.config import ExtractConfig

    cfg = ExtractConfig(kg_python_plugin="plugin:demo@1.0.0:kg")

    assert cfg.kg_python_plugin == "plugin:demo@1.0.0:kg"


def test_document_kg_plugin_derives_ref_without_inheriting_chunk_params(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.api.routes as routes

    monkeypatch.setattr(
        routes,
        "derive_registered_stage_plugin_ref",
        lambda plugin_ref, stage: "plugin:demo@1.0.0:kg" if plugin_ref and stage == "kg" else "",
        raising=True,
    )
    document = SimpleNamespace(
        doc_metadata={
            "pipeline_effective": {
                "chunk_python_plugin": "plugin:demo@1.0.0:chunk",
                "chunk_python_params": {"chunk_only": 1600},
                "kg_python_params": {},
            }
        }
    )

    plugin_ref, params = routes._document_kg_python_plugin(document)  # type: ignore[arg-type]

    assert plugin_ref == "plugin:demo@1.0.0:kg"
    assert params == {}


@pytest.mark.asyncio
async def test_event_extractor_uses_kg_python_plugin_before_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.types.indexing import EventEntityInput, IndexKind, IndexRecord

    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: _Session(), raising=True)

    async def _should_not_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("kg_python_plugin path must not create an LLM client")

    monkeypatch.setattr(extractor_mod, "create_llm_client", _should_not_create_llm_client, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(tenant_id=tenant_id, document_id=document_id, chunk_id=chunk_id)
    called: dict[str, object] = {}

    def _fake_apply_kg_python_plugin(documents, *, plugin_ref, params=None, context=None):  # noqa: ANN001
        called["plugin_ref"] = plugin_ref
        called["params"] = params
        called["context"] = context
        called["metadata"] = dict(documents[0].metadata or {})
        return [
            IndexRecord(
                kind=IndexKind.EVENT,
                title="Demo case: account renewal",
                summary="Account renewal material",
                content="Account renewal requires identity proof",
                document_id=document_id,
                chunk_id=chunk_id,
                references={"pipeline_hash": "ph-plugin"},
                entities=[
                    EventEntityInput(
                        name="Account renewal",
                        normalized_name="account_renewal",
                        type="DemoRecord",
                        role="subject",
                    )
                ],
            )
        ]

    monkeypatch.setattr(extractor_mod, "apply_kg_python_plugin", _fake_apply_kg_python_plugin, raising=True)

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def upsert(self, **kwargs):  # noqa: ANN003
            records = kwargs["records"]
            assert len(records) == 1
            assert records[0].kind == IndexKind.EVENT
            return SimpleNamespace(
                event_result=SimpleNamespace(
                    events=[SimpleNamespace(id=UUID(int=10), chunk_id=chunk_id, document_id=document_id)],
                    entities=[SimpleNamespace(id=UUID(int=11))],
                )
            )

    monkeypatch.setattr(extractor_mod, "Indexer", _FakeIndexer, raising=True)

    cfg = ExtractConfig(
        chunk_ids=[chunk_id],
        tenant_id=tenant_id,
        replace_existing=False,
        kg_python_plugin="plugin:demo@1.0.0:kg",
        kg_python_params={"profile": "demo"},
    )
    events = await extractor_mod.EventExtractor().extract(cfg, chunks=[chunk])

    assert len(events) == 1
    assert called["plugin_ref"] == "plugin:demo@1.0.0:kg"
    assert called["params"] == {"profile": "demo"}
    assert called["context"] == {"tenant_id": str(tenant_id)}
    assert called["metadata"] == {
        "source_record_id": "record-1",
        "chunk_kind": "demo_case_full",
        "pipeline_hash": "ph-plugin",
        "document_id": str(document_id),
        "chunk_id": str(chunk_id),
        "chunk_index": 7,
        "start_char": 10,
        "end_char": 30,
    }


@pytest.mark.asyncio
async def test_event_extractor_applies_chunk_budget_before_kg_python_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.extraction.extractor as extractor_mod
    from app.core import config as config_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.types.indexing import EventEntityInput, IndexKind, IndexRecord

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT", 3, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CHUNKS_PER_DOCUMENT_STRATEGY", "uniform", raising=False)
    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: _Session(), raising=True)

    async def _should_not_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("kg_python_plugin path must not create an LLM client")

    monkeypatch.setattr(extractor_mod, "create_llm_client", _should_not_create_llm_client, raising=True)

    writeback_calls: list[dict[str, object]] = []

    def _capture_writeback(self, **kwargs):  # noqa: ANN001
        writeback_calls.append(kwargs)

    monkeypatch.setattr(extractor_mod.EventExtractor, "_writeback_document_metadata", _capture_writeback, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    chunks: list[_Chunk] = []
    for index in range(10):
        chunk = _Chunk(tenant_id=tenant_id, document_id=document_id, chunk_id=UUID(int=100 + index))
        chunk.chunk_index = index
        chunk.start_char = index * 10
        chunk.end_char = (index + 1) * 10
        chunk.content = f"Record {index}: account renewal requires identity proof"
        chunk.doc_metadata = {
            "source_record_id": f"record-{index}",
            "chunk_kind": "demo_case_full",
            "pipeline_hash": "ph-plugin",
        }
        chunks.append(chunk)

    called: dict[str, object] = {}

    def _fake_apply_kg_python_plugin(documents, *, plugin_ref, params=None, context=None):  # noqa: ANN001
        called["chunk_indices"] = [int(doc.metadata["chunk_index"]) for doc in documents]
        called["plugin_ref"] = plugin_ref
        return [
            IndexRecord(
                kind=IndexKind.EVENT,
                title=f"Demo event {doc.metadata['chunk_index']}",
                summary="Account renewal material",
                content=doc.page_content,
                document_id=document_id,
                chunk_id=UUID(str(doc.metadata["chunk_id"])),
                references={"pipeline_hash": "ph-plugin"},
                entities=[
                    EventEntityInput(
                        name=f"Account renewal {doc.metadata['chunk_index']}",
                        normalized_name=f"account_renewal_{doc.metadata['chunk_index']}",
                        type="DemoRecord",
                        role="subject",
                    )
                ],
            )
            for doc in documents
        ]

    monkeypatch.setattr(extractor_mod, "apply_kg_python_plugin", _fake_apply_kg_python_plugin, raising=True)

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def upsert(self, **kwargs):  # noqa: ANN003
            records = kwargs["records"]
            return SimpleNamespace(
                event_result=SimpleNamespace(
                    events=[
                        SimpleNamespace(id=UUID(int=1000 + i), chunk_id=record.chunk_id, document_id=record.document_id)
                        for i, record in enumerate(records)
                    ],
                    entities=[],
                )
            )

    monkeypatch.setattr(extractor_mod, "Indexer", _FakeIndexer, raising=True)

    cfg = ExtractConfig(
        chunk_ids=[chunk.id for chunk in chunks],
        tenant_id=tenant_id,
        replace_existing=False,
        kg_python_plugin="plugin:demo@1.0.0:kg",
    )
    events = await extractor_mod.EventExtractor().extract(cfg, chunks=chunks)

    assert len(events) == 3
    assert called["plugin_ref"] == "plugin:demo@1.0.0:kg"
    assert called["chunk_indices"] == [0, 4, 9]
    assert len(writeback_calls) == 1
    assert len(writeback_calls[0]["budget_skipped_chunk_ids"]) == 7
    assert writeback_calls[0]["budget_stats_by_doc"][document_id] == {
        "strategy": "uniform",
        "total": 10,
        "kept": 3,
        "skipped": 7,
    }
