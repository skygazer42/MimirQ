from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.documents import Document

DEMO_GOVERNANCE_REF = "plugin:demo-runtime-plugin@1.0.0:governance"
DEMO_CHUNK_REF = "plugin:demo-runtime-plugin@1.0.0:chunk"
DEMO_KG_REF = "plugin:demo-runtime-plugin@1.0.0:kg"
LEGACY_IMPORT_GOVERNANCE_REF = "tests.fixtures.python_pipeline_import_plugin:govern_documents"

SAMPLE_RECORDS = """Title: Alpha onboarding
Owner: Operations
Answer: Complete identity proofing before activation.
--RECORD--
Title: Beta renewal
Owner: Support
Answer: Renew the account from the admin portal.
"""


def _write_demo_runtime_plugin(tmp_path: Path) -> dict[str, object]:
    from app.rag.pipeline_plugins.registry import describe_plugin_dir

    plugin_root = tmp_path / "plugins"
    plugin_dir = plugin_root / "demo-runtime-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mimirq-plugin.json").write_text(
        json.dumps(
            {
                "id": "demo-runtime-plugin",
                "version": "1.0.0",
                "name": "Demo Runtime Plugin",
                "description": "Neutral test plugin for platform runtime coverage",
                "status": "published",
                "entry": {
                    "governance": "plugin.py:govern_documents",
                    "chunk": "plugin.py:chunk_documents",
                    "kg": "plugin.py:build_kg_events",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """
from langchain_core.documents import Document


def _field(text, name, default=""):
    prefix = f"{name}:"
    for line in str(text or "").splitlines():
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return default


def govern_documents(documents, params=None, context=None):
    params = dict(params or {})
    separator = params.get("separator") or "--RECORD--"
    out = []
    for doc in documents:
        parts = [part.strip() for part in str(doc.page_content or "").split(separator) if part.strip()]
        for index, part in enumerate(parts):
            name = _field(part, "Title", f"record-{index + 1}")
            meta = dict(doc.metadata or {})
            meta.update(
                {
                    "business_type": "demo_case",
                    "record_name": name,
                    "record_index": index,
                    "source_record_id": f"{meta.get('source', 'demo-source')}#{index}",
                }
            )
            out.append(Document(page_content=part, metadata=meta))
    return out


def chunk_documents(documents, params=None, context=None):
    max_chars = int((params or {}).get("demo_max_chars") or 1600)
    chunks = []
    for doc in documents:
        text = str(doc.page_content or "")
        meta = dict(doc.metadata or {})
        if len(text) <= max_chars:
            chunks.append(
                Document(
                    page_content=text,
                    metadata={**meta, "chunk_kind": "demo_record_full", "chunk_strategy": "demo_runtime_python"},
                )
            )
            continue
        for offset in range(0, len(text), max_chars):
            chunks.append(
                Document(
                    page_content=text[offset : offset + max_chars],
                    metadata={
                        **meta,
                        "chunk_kind": "demo_record_part",
                        "chunk_strategy": "demo_runtime_python",
                        "part_index": offset // max_chars,
                    },
                )
            )
    return chunks


def build_kg_events(documents, params=None, context=None):
    events = []
    for doc in documents:
        meta = dict(doc.metadata or {})
        name = meta.get("record_name") or "demo"
        events.append(
            {
                "title": f"Demo record: {name}",
                "summary": f"Demo record {name}",
                "content": doc.page_content,
                "references": {"source_record_id": meta.get("source_record_id")},
                "extra_data": {"kg_builder": "demo_runtime_plugin_v1"},
                "entities": [
                    {"name": name, "type": "DemoRecord", "role": "subject"},
                    {"name": meta.get("business_type", "demo_case"), "type": "BusinessType", "role": "category"},
                ],
            }
        )
    return events
""".strip(),
        encoding="utf-8",
    )
    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    (plugin_dir / ".mimirq-plugin-test.json").write_text(
        json.dumps(
            {
                "plugin_id": descriptor.id,
                "version": descriptor.version,
                "package_hash": descriptor.package_hash,
                "passed": True,
                "stages": {
                    "governance": {
                        "passed": True,
                        "input_count": 1,
                        "output_count": 2,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                    "chunk": {
                        "passed": True,
                        "input_count": 2,
                        "output_count": 2,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                    "kg": {
                        "passed": True,
                        "input_count": 2,
                        "output_count": 2,
                        "kg_validation": {"ok": True, "errors": []},
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return {"plugin_directories": [str(plugin_root)], "require_test_report": False}


def test_registered_governance_plugin_extracts_records_and_metadata(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import apply_governance_python_plugin

    context = _write_demo_runtime_plugin(tmp_path)
    records = apply_governance_python_plugin(
        [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
        plugin_ref=DEMO_GOVERNANCE_REF,
        context=context,
    )

    assert len(records) == 2
    assert records[0].metadata["business_type"] == "demo_case"
    assert records[0].metadata["record_name"] == "Alpha onboarding"
    assert records[0].metadata["source_record_id"] == "sample.txt#0"
    assert "Answer: Complete identity proofing" in records[0].page_content


def test_registered_document_plugin_rejects_reserved_platform_metadata_views(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import PythonPipelinePluginError, apply_governance_python_plugin

    context = _write_demo_runtime_plugin(tmp_path)
    plugin_path = tmp_path / "plugins" / "demo-runtime-plugin" / "plugin.py"
    plugin_source = plugin_path.read_text(encoding="utf-8")
    plugin_path.write_text(
        plugin_source.replace(
            '"source_record_id": f"{meta.get(\'source\', \'demo-source\')}#{index}",',
            '"source_record_id": f"{meta.get(\'source\', \'demo-source\')}#{index}",\n'
            '                    "_indexed_metadata": {"record_name": name},',
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PythonPipelinePluginError,
        match="governance plugin metadata must not contain reserved platform metadata field '_indexed_metadata'",
    ):
        apply_governance_python_plugin(
            [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
            plugin_ref=DEMO_GOVERNANCE_REF,
            context=context,
        )


def test_registered_chunk_plugin_keeps_short_record_as_one_chunk(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import apply_chunk_python_plugin, apply_governance_python_plugin

    context = _write_demo_runtime_plugin(tmp_path)
    records = apply_governance_python_plugin(
        [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
        plugin_ref=DEMO_GOVERNANCE_REF,
        context=context,
    )
    chunks = apply_chunk_python_plugin(
        records,
        plugin_ref=DEMO_CHUNK_REF,
        params={"demo_max_chars": 2000},
        context=context,
    )

    assert len(chunks) == 2
    assert chunks[0].metadata["chunk_kind"] == "demo_record_full"
    assert chunks[0].metadata["chunk_strategy"] == "demo_runtime_python"
    assert chunks[0].metadata["record_name"] == "Alpha onboarding"
    assert "Owner: Operations" in chunks[0].page_content


def test_registered_chunk_plugin_input_excludes_platform_metadata_views(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import apply_chunk_python_plugin, apply_governance_python_plugin

    context = _write_demo_runtime_plugin(tmp_path)
    _attach_runtime_plugin_metadata_schema(
        tmp_path / "plugins" / "demo-runtime-plugin",
        {
            "schema": "mimirq.metadata_schema.v1",
            "fields": [
                {
                    "name": "business_type",
                    "type": "string",
                    "required": True,
                    "stages": ["governance", "chunk"],
                    "filterable": True,
                }
            ],
        },
    )
    plugin_path = tmp_path / "plugins" / "demo-runtime-plugin" / "plugin.py"
    plugin_source = plugin_path.read_text(encoding="utf-8")
    plugin_path.write_text(
        plugin_source.replace(
            "        meta = dict(doc.metadata or {})\n        if len(text) <= max_chars:",
            "        meta = dict(doc.metadata or {})\n"
            "        if '_indexed_metadata' in meta:\n"
            "            raise AssertionError('platform metadata view leaked into chunk plugin input')\n"
            "        if len(text) <= max_chars:",
        ),
        encoding="utf-8",
    )
    records = apply_governance_python_plugin(
        [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
        plugin_ref=DEMO_GOVERNANCE_REF,
        context=context,
    )

    assert records[0].metadata["_indexed_metadata"] == {"business_type": "demo_case"}

    chunks = apply_chunk_python_plugin(
        records,
        plugin_ref=DEMO_CHUNK_REF,
        params={"demo_max_chars": 2000},
        context=context,
    )

    assert chunks[0].metadata["_indexed_metadata"] == {"business_type": "demo_case"}


def test_registered_plugin_governance_runs_before_builtin_cleanup(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import apply_chunk_python_plugin, apply_governance_python_plugin
    from app.rag.preprocessing.processor import governance_processor

    context = _write_demo_runtime_plugin(tmp_path)
    records = apply_governance_python_plugin(
        [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
        plugin_ref=DEMO_GOVERNANCE_REF,
        context=context,
    )
    cleaned_records, _stats = governance_processor.clean_documents(
        records,
        remove_toc_lines=True,
        remove_noise_lines=True,
        unwrap_lines=True,
        remove_common_lines=True,
        noise_min_chars=2,
        noise_ratio_threshold=0.2,
        common_lines_min_docs=3,
        common_lines_min_ratio=0.35,
        unwrap_max_line_length=120,
    )
    chunks = apply_chunk_python_plugin(
        cleaned_records,
        plugin_ref=DEMO_CHUNK_REF,
        params={"demo_max_chars": 2000},
        context=context,
    )

    assert [record.metadata["record_name"] for record in cleaned_records] == ["Alpha onboarding", "Beta renewal"]
    assert [chunk.metadata["record_name"] for chunk in chunks] == ["Alpha onboarding", "Beta renewal"]
    assert "Title: Alpha onboarding" in chunks[0].page_content
    assert "Owner: Operations" in chunks[0].page_content


def test_registered_kg_plugin_builds_deterministic_events_from_chunks(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import (
        apply_chunk_python_plugin,
        apply_governance_python_plugin,
        apply_kg_python_plugin,
    )
    from app.types.indexing import IndexKind

    context = _write_demo_runtime_plugin(tmp_path)
    records = apply_governance_python_plugin(
        [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
        plugin_ref=DEMO_GOVERNANCE_REF,
        context=context,
    )
    chunks = apply_chunk_python_plugin(
        records,
        plugin_ref=DEMO_CHUNK_REF,
        params={"demo_max_chars": 2000},
        context=context,
    )
    events = apply_kg_python_plugin(chunks, plugin_ref=DEMO_KG_REF, context=context)

    assert len(events) == 2
    first = events[0]
    assert first.kind == IndexKind.EVENT
    assert first.title == "Demo record: Alpha onboarding"
    assert first.references["source_record_id"] == chunks[0].metadata["source_record_id"]
    assert first.extra_data["kg_builder"] == "demo_runtime_plugin_v1"
    entity_pairs = {(entity.type, entity.name, entity.role) for entity in first.entities}
    assert ("DemoRecord", "Alpha onboarding", "subject") in entity_pairs
    assert ("BusinessType", "demo_case", "category") in entity_pairs


def _attach_runtime_plugin_metadata_schema(plugin_dir: Path, schema: dict[str, object]) -> None:
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metadata_schema"] = "metadata_schema.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (plugin_dir / "metadata_schema.json").write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")


def test_registered_kg_plugin_rejects_missing_event_metadata_contract(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import (
        PythonPipelinePluginError,
        apply_chunk_python_plugin,
        apply_governance_python_plugin,
        apply_kg_python_plugin,
    )

    context = _write_demo_runtime_plugin(tmp_path)
    _attach_runtime_plugin_metadata_schema(
        tmp_path / "plugins" / "demo-runtime-plugin",
        {
            "schema": "mimirq.metadata_schema.v1",
            "fields": [
                {
                    "name": "extra_data.required_marker",
                    "type": "string",
                    "required": True,
                    "stages": ["kg"],
                }
            ],
        },
    )
    records = apply_governance_python_plugin(
        [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
        plugin_ref=DEMO_GOVERNANCE_REF,
        context=context,
    )
    chunks = apply_chunk_python_plugin(
        records,
        plugin_ref=DEMO_CHUNK_REF,
        params={"demo_max_chars": 2000},
        context=context,
    )

    with pytest.raises(PythonPipelinePluginError, match="plugin KG metadata contract failed for extra_data.required_marker: required"):
        apply_kg_python_plugin(chunks, plugin_ref=DEMO_KG_REF, context=context)


def test_registered_kg_plugin_accepts_event_metadata_contract(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import (
        apply_chunk_python_plugin,
        apply_governance_python_plugin,
        apply_kg_python_plugin,
    )

    context = _write_demo_runtime_plugin(tmp_path)
    _attach_runtime_plugin_metadata_schema(
        tmp_path / "plugins" / "demo-runtime-plugin",
        {
            "schema": "mimirq.metadata_schema.v1",
            "fields": [
                {
                    "name": "extra_data.kg_builder",
                    "type": "string",
                    "required": True,
                    "stages": ["kg"],
                },
                {
                    "name": "references.source_record_id",
                    "type": "string",
                    "required": True,
                    "stages": ["kg"],
                },
            ],
        },
    )
    records = apply_governance_python_plugin(
        [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
        plugin_ref=DEMO_GOVERNANCE_REF,
        context=context,
    )
    chunks = apply_chunk_python_plugin(
        records,
        plugin_ref=DEMO_CHUNK_REF,
        params={"demo_max_chars": 2000},
        context=context,
    )

    events = apply_kg_python_plugin(chunks, plugin_ref=DEMO_KG_REF, context=context)

    assert events[0].extra_data["kg_builder"] == "demo_runtime_plugin_v1"
    assert events[0].references["source_record_id"] == "sample.txt#0"


def test_registered_kg_plugin_rejects_reserved_platform_metadata_views(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import (
        PythonPipelinePluginError,
        apply_chunk_python_plugin,
        apply_governance_python_plugin,
        apply_kg_python_plugin,
    )

    context = _write_demo_runtime_plugin(tmp_path)
    plugin_path = tmp_path / "plugins" / "demo-runtime-plugin" / "plugin.py"
    plugin_source = plugin_path.read_text(encoding="utf-8")
    plugin_path.write_text(
        plugin_source.replace(
            '"references": {"source_record_id": meta.get("source_record_id")},',
            '"references": {"source_record_id": meta.get("source_record_id")},\n'
            '                "metadata": {"_indexed_metadata": {"record_name": name}},',
        ),
        encoding="utf-8",
    )
    records = apply_governance_python_plugin(
        [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
        plugin_ref=DEMO_GOVERNANCE_REF,
        context=context,
    )
    chunks = apply_chunk_python_plugin(
        records,
        plugin_ref=DEMO_CHUNK_REF,
        params={"demo_max_chars": 2000},
        context=context,
    )

    with pytest.raises(
        PythonPipelinePluginError,
        match="kg plugin metadata must not contain reserved platform metadata field '_indexed_metadata'",
    ):
        apply_kg_python_plugin(chunks, plugin_ref=DEMO_KG_REF, context=context)


def test_registered_plugin_runtime_rejects_cross_stage_refs(tmp_path: Path):
    from app.rag.pipeline_plugins.runtime import (
        PythonPipelinePluginError,
        apply_chunk_python_plugin,
        apply_governance_python_plugin,
        apply_kg_python_plugin,
    )

    context = _write_demo_runtime_plugin(tmp_path)
    documents = [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})]

    with pytest.raises(PythonPipelinePluginError, match="registered plugin ref must target the governance stage"):
        apply_governance_python_plugin(documents, plugin_ref=DEMO_CHUNK_REF, context=context)

    with pytest.raises(PythonPipelinePluginError, match="registered plugin ref must target the chunk stage"):
        apply_chunk_python_plugin(documents, plugin_ref=DEMO_GOVERNANCE_REF, context=context)

    with pytest.raises(PythonPipelinePluginError, match="registered plugin ref must target the kg stage"):
        apply_kg_python_plugin(documents, plugin_ref=DEMO_CHUNK_REF, context=context)


def test_kg_runtime_does_not_infer_plugin_reference_fields_from_chunk_metadata():
    from app.rag.pipeline_plugins.runtime import _coerce_kg_events

    source = Document(
        page_content="Demo source content",
        metadata={
            "source": "sample.txt",
            "source_record_id": "sample.txt#0",
            "chunk_kind": "demo_record_full",
            "pipeline_hash": "ph-plugin",
        },
    )

    events = _coerce_kg_events(
        [{"title": "Demo event", "summary": "Demo summary", "content": "Demo source content"}],
        documents=[source],
        plugin_ref=DEMO_KG_REF,
    )

    assert events[0].references["source"] == "sample.txt"
    assert events[0].references["pipeline_hash"] == "ph-plugin"
    assert events[0].references["kg_python_plugin"] == DEMO_KG_REF
    assert "source_record_id" not in events[0].references
    assert "chunk_kind" not in events[0].references


def test_python_plugin_runtime_rejects_disallowed_import_prefix():
    from app.rag.pipeline_plugins.runtime import PythonPipelinePluginError, apply_governance_python_plugin

    with pytest.raises(PythonPipelinePluginError):
        apply_governance_python_plugin([], plugin_ref="os:path")


def test_python_plugin_runtime_disables_import_refs_when_allowlist_is_blank(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import settings
    from app.rag.pipeline_plugins.runtime import PythonPipelinePluginError, apply_governance_python_plugin

    monkeypatch.setattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "", raising=False)

    with pytest.raises(PythonPipelinePluginError, match="python plugin import refs are disabled"):
        apply_governance_python_plugin(
            [],
            plugin_ref=LEGACY_IMPORT_GOVERNANCE_REF,
        )


def test_python_plugin_runtime_allows_import_refs_only_when_prefix_configured(monkeypatch: pytest.MonkeyPatch):
    from app.core.config import settings
    from app.rag.pipeline_plugins.runtime import apply_governance_python_plugin

    monkeypatch.setattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "tests.fixtures.", raising=False)

    docs = apply_governance_python_plugin(
        [],
        plugin_ref=LEGACY_IMPORT_GOVERNANCE_REF,
    )

    assert [doc.page_content for doc in docs] == ["legacy import governance fixture"]


def test_python_import_governance_plugin_rejects_reserved_platform_metadata_views(
    monkeypatch: pytest.MonkeyPatch,
):
    import tests.fixtures.python_pipeline_import_plugin as fixture
    from app.core.config import settings
    from app.rag.pipeline_plugins.runtime import PythonPipelinePluginError, apply_governance_python_plugin

    def govern_with_reserved_metadata(documents, params=None, context=None):  # noqa: ANN001
        return [
            Document(
                page_content="legacy import governance fixture",
                metadata={"_indexed_metadata": {"record_key": "demo"}},
            )
        ]

    monkeypatch.setattr(settings, "PYTHON_PIPELINE_PLUGIN_ALLOW_PREFIXES", "tests.fixtures.", raising=False)
    monkeypatch.setattr(fixture, "govern_documents", govern_with_reserved_metadata)

    with pytest.raises(
        PythonPipelinePluginError,
        match="governance plugin metadata must not contain reserved platform metadata field '_indexed_metadata'",
    ):
        apply_governance_python_plugin([], plugin_ref=LEGACY_IMPORT_GOVERNANCE_REF)


def test_pipeline_config_round_trips_python_plugin_fields():
    from app.services.pipeline_config import build_pipeline_metadata, resolve_pipeline_options
    from app.types.pipeline import PipelineOptions

    opts = PipelineOptions(
        governance_python_plugin=DEMO_GOVERNANCE_REF,
        governance_python_params={"profile": "demo"},
        chunk_python_plugin=DEMO_CHUNK_REF,
        chunk_python_params={"demo_max_chars": 1500},
    )

    meta = build_pipeline_metadata(opts)
    assert meta == {
        "governance": {
            "python_plugin": DEMO_GOVERNANCE_REF,
            "python_params": {"profile": "demo"},
        },
        "chunk_python_plugin": DEMO_CHUNK_REF,
        "chunk_python_params": {"demo_max_chars": 1500},
    }

    effective = resolve_pipeline_options(opts)
    assert effective.governance_python_plugin == DEMO_GOVERNANCE_REF
    assert effective.chunk_python_plugin == DEMO_CHUNK_REF
    assert effective.chunk_python_params == {"demo_max_chars": 1500}


def test_chunking_stage_uses_registered_python_plugin_when_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from app.core.config import settings
    from app.parsing.processors.processor import ChunkingStage
    from app.rag.pipeline_plugins.runtime import apply_governance_python_plugin

    context = _write_demo_runtime_plugin(tmp_path)
    monkeypatch.setattr(settings, "PYTHON_PIPELINE_PLUGIN_DIRS", str(tmp_path / "plugins"), raising=False)
    records = apply_governance_python_plugin(
        [Document(page_content=SAMPLE_RECORDS, metadata={"source": "sample.txt"})],
        plugin_ref=DEMO_GOVERNANCE_REF,
        context=context,
    )
    result = ChunkingStage().run(
        documents=records,
        chunk_strategy="langchain_recursive",
        chunk_size=1000,
        chunk_overlap=100,
        chunk_python_plugin=DEMO_CHUNK_REF,
        chunk_python_params={"demo_max_chars": 2000},
    )

    assert len(result.chunks) == 2
    assert result.chunks[0].metadata["chunk_strategy"] == "demo_runtime_python"
