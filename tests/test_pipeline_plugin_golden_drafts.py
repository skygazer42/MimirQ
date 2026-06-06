from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError


class _Chunk:
    def __init__(self, *, document_id: UUID, content: str, metadata: dict, chunk_index: int = 0):
        self.id = uuid4()
        self.document_id = document_id
        self.chunk_index = chunk_index
        self.content = content
        self.doc_metadata = metadata
        self.page_number = 1
        self.start_char = 3
        self.end_char = 30


def _metadata_with_evaluable(metadata: dict, *fields: str) -> dict:
    out = dict(metadata)
    out["_evaluable_metadata"] = {field: out[field] for field in fields if field in out}
    return out


def test_pipeline_plugin_golden_draft_request_requires_registered_chunk_plugin_ref():
    from app.api.schemas.pipeline import PipelinePluginGoldenDraftRequest

    dataset_id = uuid4()
    PipelinePluginGoldenDraftRequest(dataset_id=dataset_id, plugin_ref="plugin:demo-plugin@1.0.0:chunk")

    for plugin_ref in (
        "plugin:demo-plugin@1.0.0:governance",
        "plugin:demo-plugin@1.0.0:kg",
        "app.rag.pipeline_plugins.demo:chunk_documents",
    ):
        with pytest.raises(ValidationError, match="plugin_ref must be a registered chunk plugin ref"):
            PipelinePluginGoldenDraftRequest(dataset_id=dataset_id, plugin_ref=plugin_ref)


def test_build_golden_draft_bundle_from_plugin_rules_generates_reference_sources():
    from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks

    dataset_id = uuid4()
    document_id = uuid4()
    chunk = _Chunk(
        document_id=document_id,
        content="Answer: identity proof and a signed form.",
        metadata=_metadata_with_evaluable(
            {
                "record_name": "Demo record",
                "knowledge_type": "demo_case",
                "source_record_id": "record-1",
                "chunk_kind": "demo_materials",
                "pipeline_hash": "ph_123",
                "doc_pipeline_key": f"{document_id}:ph_123",
            },
            "source_record_id",
            "chunk_kind",
        ),
    )
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["source_record_id", "chunk_kind"],
        "template_selector_fields": ["knowledge_type"],
        "tag_fields": ["knowledge_type", "chunk_kind"],
        "query_templates": {
            "demo_case": ["What materials does {record_name} require?", "{missing} will not render"],
        },
    }

    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=[chunk],
        golden_rules=golden_rules,
        plugin_id="demo-plugin",
        max_items=10,
    )

    assert bundle["schema"] == "mimirq.regression_cases.v1"
    assert bundle["dataset_id"] == str(dataset_id)
    assert len(bundle["items"]) == 1
    item = bundle["items"][0]
    assert item["question"] == "What materials does Demo record require?"
    assert item["expected_answer"] == "Answer: identity proof and a signed form."
    assert item["tags"] == ["plugin:demo-plugin", "golden_draft", "demo_case", "demo_materials"]
    assert item["reference_sources"][0]["document_id"] == str(document_id)
    assert item["reference_sources"][0]["chunk_id"] == str(chunk.id)
    assert item["reference_sources"][0]["pipeline_hash"] == "ph_123"
    assert item["reference_sources"][0]["quote"] == "Answer: identity proof and a signed form."
    assert item["extra"]["expected_metadata"] == {"source_record_id": "record-1", "chunk_kind": "demo_materials"}


def test_build_golden_draft_bundle_does_not_score_raw_business_metadata_without_evaluable_view():
    from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks

    chunk = _Chunk(
        document_id=uuid4(),
        content="Answer: raw business metadata is not enough.",
        metadata={
            "record_name": "Demo record",
            "knowledge_type": "demo_case",
            "source_record_id": "record-1",
        },
    )
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["source_record_id"],
        "template_selector_fields": ["knowledge_type"],
        "query_templates": {"demo_case": ["What does {record_name} require?"]},
    }

    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=uuid4(),
        chunks=[chunk],
        golden_rules=golden_rules,
        plugin_id="demo-plugin",
        max_items=10,
    )

    assert bundle["items"] == []


def test_build_golden_draft_bundle_reads_dotted_expected_metadata_as_declared_field_name():
    from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks

    chunk = _Chunk(
        document_id=uuid4(),
        content="Answer: dotted metadata fields are schema-declared names.",
        metadata={
            "record_name": "Demo record",
            "record.identity": "record-1",
            "_evaluable_metadata": {"record.identity": "record-1"},
        },
    )
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["record.identity"],
        "query_templates": {"default": ["What is {record_name}?"]},
    }

    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=uuid4(),
        chunks=[chunk],
        golden_rules=golden_rules,
        plugin_id="demo-plugin",
        max_items=10,
    )

    assert bundle["items"][0]["extra"]["expected_metadata"] == {"record.identity": "record-1"}


def test_build_golden_draft_bundle_uses_plugin_declared_selector_and_tag_fields():
    from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks

    dataset_id = uuid4()
    document_id = uuid4()
    chunk = _Chunk(
        document_id=document_id,
        content="Answer: upload identity proof and a signed form.",
        metadata=_metadata_with_evaluable(
            {
                "case_name": "Demo service",
                "business_type": "demo_case",
                "segment_kind": "answer_materials",
                "source_record_id": "record-1",
            },
            "source_record_id",
            "business_type",
        ),
    )
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["source_record_id", "business_type"],
        "template_selector_fields": ["segment_kind", "business_type"],
        "tag_fields": ["business_type", "segment_kind"],
        "query_templates": {
            "demo_case": ["{case_name} generic fallback question?"],
            "answer_materials": ["What materials does {case_name} require?"],
        },
    }

    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=[chunk],
        golden_rules=golden_rules,
        plugin_id="demo-plugin",
        max_items=10,
    )

    assert [item["question"] for item in bundle["items"]] == ["What materials does Demo service require?"]
    assert bundle["items"][0]["tags"] == [
        "plugin:demo-plugin",
        "golden_draft",
        "demo_case",
        "answer_materials",
    ]
    assert bundle["items"][0]["extra"]["expected_metadata"] == {
        "source_record_id": "record-1",
        "business_type": "demo_case",
    }


def test_build_golden_draft_bundle_does_not_infer_plugin_fields_without_declarations():
    from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks

    dataset_id = uuid4()
    document_id = uuid4()
    chunk = _Chunk(
        document_id=document_id,
        content="Answer: platform should not infer plugin field meanings.",
        metadata=_metadata_with_evaluable(
            {
                "record_name": "Demo record",
                "knowledge_type": "demo_case",
                "source_record_id": "record-1",
                "chunk_kind": "demo_materials",
            },
            "source_record_id",
        ),
    )
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["source_record_id"],
        "query_templates": {
            "demo_case": ["Broad inferred question for {record_name}?"],
            "demo_materials": ["Specific inferred question for {record_name}?"],
            "default": ["Default question for {record_name}?"],
        },
    }

    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=[chunk],
        golden_rules=golden_rules,
        plugin_id="demo-plugin",
        max_items=10,
    )

    assert [item["question"] for item in bundle["items"]] == ["Default question for Demo record?"]
    assert bundle["items"][0]["tags"] == ["plugin:demo-plugin", "golden_draft"]
    assert bundle["items"][0]["extra"]["expected_metadata"] == {"source_record_id": "record-1"}


def test_build_golden_draft_bundle_carries_plugin_record_identity_reference():
    from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks

    dataset_id = uuid4()
    document_id = uuid4()
    chunk = _Chunk(
        document_id=document_id,
        content="Location: service desk.",
        metadata=_metadata_with_evaluable(
            {
                "source_record_id": "record-1",
                "knowledge_section": "demo_section",
                "chunk_kind": "demo_location",
                "_record_identity": {
                    "schema": "mimirq.record_identity.v1",
                    "key": "knowledge_section=demo_section|source_record_id=record-1",
                    "fields": {
                        "knowledge_section": "demo_section",
                        "source_record_id": "record-1",
                    },
                },
            },
            "source_record_id",
            "knowledge_section",
        ),
    )
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["source_record_id", "knowledge_section"],
        "template_selector_fields": ["chunk_kind"],
        "query_templates": {"demo_location": ["Where is the demo record handled?"]},
    }

    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=[chunk],
        golden_rules=golden_rules,
        plugin_id="demo-plugin",
        max_items=10,
    )

    assert bundle["items"][0]["reference_sources"][0]["record_identity"] == {
        "schema": "mimirq.record_identity.v1",
        "key": "knowledge_section=demo_section|source_record_id=record-1",
        "fields": {
            "knowledge_section": "demo_section",
            "source_record_id": "record-1",
        },
    }


def test_build_golden_draft_bundle_dedupes_questions_and_skips_missing_expected_metadata():
    from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks

    dataset_id = uuid4()
    document_id = uuid4()
    good_meta = {
        "question": "Demo question?",
        "knowledge_type": "faq",
        "source_record_id": "record-1",
        "chunk_kind": "qa_pair",
    }
    chunks = [
        _Chunk(
            document_id=document_id,
            content="Answer: one",
            metadata=_metadata_with_evaluable(good_meta, "source_record_id"),
        ),
        _Chunk(
            document_id=document_id,
            content="Answer: duplicate",
            metadata=_metadata_with_evaluable({**good_meta, "source_record_id": "record-2"}, "source_record_id"),
        ),
        _Chunk(
            document_id=document_id,
            content="Answer: missing metadata",
            metadata={"question": "Missing field question?", "knowledge_type": "faq", "chunk_kind": "qa_pair"},
        ),
    ]
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["source_record_id"],
        "template_selector_fields": ["knowledge_type"],
        "query_templates": {"faq": ["{question}"]},
    }

    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=chunks,
        golden_rules=golden_rules,
        plugin_id="demo-plugin",
        max_items=10,
    )

    assert [item["question"] for item in bundle["items"]] == ["Demo question?"]
    assert bundle["items"][0]["extra"]["expected_metadata"] == {"source_record_id": "record-1"}


def test_build_golden_draft_bundle_prefers_chunk_kind_templates_over_broad_knowledge_type():
    from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks

    dataset_id = uuid4()
    document_id = uuid4()
    chunk = _Chunk(
        document_id=document_id,
        content="Answer: identity proof and a signed form.",
        metadata=_metadata_with_evaluable(
            {
                "record_name": "Demo record",
                "knowledge_type": "demo_case",
                "source_record_id": "record-1",
                "chunk_kind": "demo_materials",
            },
            "source_record_id",
            "chunk_kind",
        ),
    )
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["source_record_id", "chunk_kind"],
        "template_selector_fields": ["chunk_kind", "knowledge_type"],
        "query_templates": {
            "demo_case": ["How do I handle {record_name}?"],
            "demo_materials": ["What materials does {record_name} require?"],
        },
    }

    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=[chunk],
        golden_rules=golden_rules,
        plugin_id="demo-plugin",
        max_items=10,
    )

    assert [item["question"] for item in bundle["items"]] == ["What materials does Demo record require?"]
    assert bundle["items"][0]["extra"]["expected_metadata"] == {
        "source_record_id": "record-1",
        "chunk_kind": "demo_materials",
    }


def test_pipeline_plugin_golden_draft_endpoint_returns_review_bundle(monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.api.v1.pipeline as pipeline_module
    from app.api.dependencies.auth import get_current_account_id
    from app.api.dependencies.tenant import get_tenant_id
    from app.core.database import get_db

    dataset_id = uuid4()
    document_id = uuid4()
    chunk = _Chunk(
        document_id=document_id,
        content="Answer: submit the required documents.",
        metadata=_metadata_with_evaluable(
            {
                "question": "Demo question?",
                "knowledge_type": "faq",
                "source_record_id": "record-1",
                "chunk_kind": "qa_pair",
            },
            "source_record_id",
        ),
    )

    class _Descriptor:
        id = "demo-plugin"
        version = "1.0.0"
        published = True
        executable = True
        test_status = "passed"
        package_hash = "pkg_hash_123"
        golden_rules = {
            "schema": "mimirq.golden_rules.v1",
            "expected_metadata": ["source_record_id"],
            "template_selector_fields": ["knowledge_type"],
            "query_templates": {"faq": ["{question}"]},
        }

    monkeypatch.setattr(
        pipeline_module,
        "resolve_registered_plugin_descriptor",
        lambda _plugin_ref: _Descriptor(),
        raising=True,
    )
    monkeypatch.setattr(
        pipeline_module,
        "_load_plugin_golden_draft_chunks",
        lambda **_kwargs: [chunk],
        raising=True,
    )
    monkeypatch.setattr(pipeline_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(pipeline_module.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(
        pipeline_module.DatasetService,
        "assert_dataset_readable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_tenant_id] = lambda: UUID(int=1)
    app.dependency_overrides[get_current_account_id] = lambda: "tester"
    app.post("/api/v1/pipeline/plugins/golden-draft")(pipeline_module.build_pipeline_plugin_golden_draft)
    client = TestClient(app)

    res = client.post(
        "/api/v1/pipeline/plugins/golden-draft",
        json={
            "dataset_id": str(dataset_id),
            "plugin_ref": "plugin:demo-plugin@1.0.0:chunk",
            "max_items": 10,
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["plugin_id"] == "demo-plugin"
    assert body["plugin_version"] == "1.0.0"
    assert body["items_total"] == 1
    assert body["bundle"]["schema"] == "mimirq.regression_cases.v1"
    assert body["bundle"]["items"][0]["question"] == "Demo question?"
    assert body["bundle"]["items"][0]["extra"]["plugin_id"] == "demo-plugin"
    assert body["bundle"]["items"][0]["extra"]["plugin_version"] == "1.0.0"
    assert body["bundle"]["items"][0]["extra"]["plugin_ref"] == "plugin:demo-plugin@1.0.0:chunk"
    assert body["bundle"]["items"][0]["extra"]["plugin_package_hash"] == "pkg_hash_123"


def test_pipeline_plugin_golden_draft_rejects_unmarked_chunks_without_debug_gate(monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.api.v1.pipeline as pipeline_module
    from app.api.dependencies.auth import get_current_account_id
    from app.api.dependencies.tenant import get_tenant_id
    from app.core.database import get_db

    dataset_id = uuid4()

    class _Descriptor:
        id = "demo-plugin"
        version = "1.0.0"
        published = True
        executable = True
        test_status = "passed"
        package_hash = "pkg_hash_123"
        golden_rules = {
            "schema": "mimirq.golden_rules.v1",
            "expected_metadata": ["source_record_id"],
            "query_templates": {"default": ["Demo question?"]},
        }

    def _unexpected_load(**_kwargs):  # noqa: ANN003
        raise AssertionError("unmarked chunk loading must be rejected before querying chunks")

    monkeypatch.setattr(
        pipeline_module,
        "resolve_registered_plugin_descriptor",
        lambda _plugin_ref: _Descriptor(),
        raising=True,
    )
    monkeypatch.setattr(pipeline_module, "_load_plugin_golden_draft_chunks", _unexpected_load, raising=True)
    monkeypatch.setattr(pipeline_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(pipeline_module.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(
        pipeline_module.DatasetService,
        "assert_dataset_readable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_tenant_id] = lambda: UUID(int=1)
    app.dependency_overrides[get_current_account_id] = lambda: "tester"
    app.post("/api/v1/pipeline/plugins/golden-draft")(pipeline_module.build_pipeline_plugin_golden_draft)
    client = TestClient(app)

    res = client.post(
        "/api/v1/pipeline/plugins/golden-draft",
        json={
            "dataset_id": str(dataset_id),
            "plugin_ref": "plugin:demo-plugin@1.0.0:chunk",
            "include_unmarked_chunks": True,
        },
    )

    assert res.status_code == 400
    assert "PYTHON_PIPELINE_PLUGIN_ALLOW_UNMARKED_GOLDEN_CHUNKS" in res.json()["detail"]


def test_pipeline_plugin_golden_draft_import_endpoint_imports_generated_bundle(monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.api.v1.pipeline as pipeline_module
    from app.api.dependencies.auth import get_current_account_id
    from app.api.dependencies.tenant import get_tenant_id
    from app.core.database import get_db

    dataset_id = uuid4()
    document_id = uuid4()
    chunk = _Chunk(
        document_id=document_id,
        content="Answer: submit the required documents.",
        metadata=_metadata_with_evaluable(
            {
                "question": "Demo question?",
                "knowledge_type": "faq",
                "source_record_id": "record-1",
                "chunk_kind": "qa_pair",
            },
            "source_record_id",
        ),
    )

    class _Descriptor:
        id = "demo-plugin"
        version = "1.0.0"
        published = True
        executable = True
        test_status = "passed"
        package_hash = "pkg_hash_123"
        golden_rules = {
            "schema": "mimirq.golden_rules.v1",
            "expected_metadata": ["source_record_id"],
            "template_selector_fields": ["knowledge_type"],
            "query_templates": {"faq": ["{question}"]},
        }

    captured: dict[str, object] = {}
    created_case_id = uuid4()

    async def _fake_import(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {
            "created": 1,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "created_case_ids": [created_case_id],
            "updated_case_ids": [],
            "case_ids": [created_case_id],
        }

    monkeypatch.setattr(
        pipeline_module,
        "resolve_registered_plugin_descriptor",
        lambda _plugin_ref: _Descriptor(),
        raising=True,
    )
    monkeypatch.setattr(
        pipeline_module,
        "_load_plugin_golden_draft_chunks",
        lambda **_kwargs: [chunk],
        raising=True,
    )
    monkeypatch.setattr(
        pipeline_module,
        "_import_plugin_golden_draft_bundle",
        _fake_import,
        raising=True,
    )
    monkeypatch.setattr(pipeline_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(pipeline_module.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(
        pipeline_module.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_tenant_id] = lambda: UUID(int=1)
    app.dependency_overrides[get_current_account_id] = lambda: "tester"
    app.post("/api/v1/pipeline/plugins/golden-draft/import")(pipeline_module.import_pipeline_plugin_golden_draft)
    client = TestClient(app)

    res = client.post(
        "/api/v1/pipeline/plugins/golden-draft/import",
        json={
            "dataset_id": str(dataset_id),
            "plugin_ref": "plugin:demo-plugin@1.0.0:chunk",
            "max_items": 10,
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["draft"]["items_total"] == 1
    assert body["import_result"] == {
        "created": 1,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "created_case_ids": [str(created_case_id)],
        "updated_case_ids": [],
        "skipped_case_ids": [],
        "case_ids": [str(created_case_id)],
    }
    assert captured["dataset_id"] == dataset_id
    assert captured["overwrite"] is False
    assert captured["max_items"] == 10


def test_pipeline_plugin_golden_draft_rejects_unexecutable_plugin(monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import app.api.v1.pipeline as pipeline_module
    from app.api.dependencies.auth import get_current_account_id
    from app.api.dependencies.tenant import get_tenant_id
    from app.core.database import get_db

    dataset_id = uuid4()

    class _Descriptor:
        id = "demo-plugin"
        version = "1.0.0"
        published = True
        executable = False
        test_status = "stale"
        package_hash = "pkg_hash_123"
        golden_rules = {
            "schema": "mimirq.golden_rules.v1",
            "expected_metadata": ["source_record_id"],
            "query_templates": {"qa": ["{question}"]},
        }

    monkeypatch.setattr(
        pipeline_module,
        "resolve_registered_plugin_descriptor",
        lambda _plugin_ref: _Descriptor(),
        raising=True,
    )
    monkeypatch.setattr(pipeline_module.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(pipeline_module.DatasetService, "get_dataset", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(
        pipeline_module.DatasetService,
        "assert_dataset_readable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: object()
    app.dependency_overrides[get_tenant_id] = lambda: UUID(int=1)
    app.dependency_overrides[get_current_account_id] = lambda: "tester"
    app.post("/api/v1/pipeline/plugins/golden-draft")(pipeline_module.build_pipeline_plugin_golden_draft)
    client = TestClient(app)

    res = client.post(
        "/api/v1/pipeline/plugins/golden-draft",
        json={
            "dataset_id": str(dataset_id),
            "plugin_ref": "plugin:demo-plugin@1.0.0:chunk",
            "max_items": 10,
        },
    )

    assert res.status_code == 409
    assert "not executable" in res.json()["detail"]
