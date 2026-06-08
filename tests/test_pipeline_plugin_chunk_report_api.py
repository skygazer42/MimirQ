from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id


def _write_api_report_plugin(plugin_root: Path) -> tuple[Path, Path]:
    plugin_dir = plugin_root / "demo-report-api"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mimirq-plugin.json").write_text(
        json.dumps(
            {
                "id": "demo-report-api",
                "version": "1.0.0",
                "name": "Demo Report API Plugin",
                "description": "Neutral plugin for report endpoint coverage",
                "status": "published",
                "entry": {
                    "governance": "plugin.py:govern_documents",
                    "chunk": "plugin.py:chunk_documents",
                    "kg": "plugin.py:build_kg_events",
                },
                "metadata_schema": "metadata_schema.json",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {
                        "name": "section_label",
                        "type": "string",
                        "stages": ["governance", "chunk"],
                        "filterable": True,
                        "display": True,
                        "evaluable": True,
                    },
                    {
                        "name": "record_label",
                        "type": "string",
                        "stages": ["governance", "chunk"],
                        "filterable": True,
                        "display": True,
                        "evaluable": True,
                    },
                    {
                        "name": "answer_kind",
                        "type": "string",
                        "stages": ["chunk"],
                        "filterable": True,
                        "display": True,
                        "evaluable": True,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "plugin.py").write_text(
        """
from langchain_core.documents import Document


def govern_documents(documents, params=None, context=None):
    out = []
    for doc in documents:
        out.append(
            Document(
                page_content=doc.page_content,
                metadata={"section_label": "alpha", "record_label": "Alpha record"},
            )
        )
    return out


def chunk_documents(documents, params=None, context=None):
    return [
        Document(
            page_content=doc.page_content,
            metadata={**dict(doc.metadata or {}), "answer_kind": "full_record", "chunk_kind": "demo_full"},
        )
        for doc in documents
    ]


def build_kg_events(documents, params=None, context=None):
    return [
        {
            "title": "Demo graph",
            "summary": doc.page_content,
            "content": doc.page_content,
            "extra_data": {"section_label": doc.metadata.get("section_label")},
            "entities": [{"name": doc.metadata.get("record_label") or "record", "type": "Record"}],
        }
        for doc in documents
    ]
""".strip(),
        encoding="utf-8",
    )
    sample_path = plugin_dir / "sample.json"
    sample_path.write_text(
        json.dumps([{"page_content": "Answer: activate the record."}], ensure_ascii=False),
        encoding="utf-8",
    )
    return plugin_dir, sample_path


def _client(monkeypatch, plugin_root: Path) -> TestClient:  # noqa: ANN001
    import app.api.v1.pipeline as pipeline_module

    monkeypatch.setattr("app.rag.pipeline_plugins.registry.settings.PYTHON_PIPELINE_PLUGIN_DIRS", str(plugin_root))

    app = FastAPI()
    app.dependency_overrides[get_current_account_id] = lambda: "tester"
    app.post("/api/v1/pipeline/plugins/chunk-report")(pipeline_module.build_pipeline_plugin_chunk_report_endpoint)
    return TestClient(app)


def test_pipeline_plugin_chunk_report_endpoint_returns_review_report(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test

    plugin_root = tmp_path / "plugins"
    plugin_dir, sample_path = _write_api_report_plugin(plugin_root)
    run_pipeline_plugin_test(plugin_dir, input_path=sample_path, stages=["governance", "chunk", "kg"])

    client = _client(monkeypatch, plugin_root)

    res = client.post(
        "/api/v1/pipeline/plugins/chunk-report",
        json={
            "plugin_ref": "plugin:demo-report-api@1.0.0:chunk",
            "input_path": "sample.json",
            "section_metadata_keys": ["section_label"],
            "title_metadata_keys": ["record_label"],
            "metadata_highlight_keys": ["section_label", "record_label", "answer_kind"],
            "max_examples_per_section": 1,
            "preview_chars": 80,
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["schema"] == "mimirq.pipeline_plugin_chunk_report.v1"
    assert body["passed"] is True
    assert body["plugin"]["id"] == "demo-report-api"
    assert body["plugin"]["input"].endswith("sample.json")
    assert body["summary"]["input_documents"] == 1
    assert body["summary"]["chunks"] == 1
    assert body["readiness"]["status"] == "passed"
    assert {check["name"]: check["passed"] for check in body["readiness"]["checks"]} == {
        "input_documents_present": True,
        "governed_records_present": True,
        "chunks_present": True,
        "metadata_fields_present": True,
        "kg_events_present": True,
    }
    assert body["sections"][0]["knowledge_section"] == "alpha"
    assert body["sections"][0]["examples"][0]["title"] == "Alpha record"
    assert body["sections"][0]["examples"][0]["metadata_focus"]["answer_kind"] == "full_record"


def test_pipeline_plugin_chunk_report_response_schema_exposes_readiness_contract() -> None:
    from app.api.schemas.pipeline import PipelinePluginChunkReportResponse

    schema = PipelinePluginChunkReportResponse.model_json_schema()
    properties = schema["properties"]

    assert "readiness" in properties
    readiness_ref = properties["readiness"]["$ref"]
    readiness_schema = schema["$defs"][readiness_ref.rsplit("/", 1)[-1]]
    assert "status" in readiness_schema["properties"]
    assert "checks" in readiness_schema["properties"]

    checks_ref = readiness_schema["properties"]["checks"]["items"]["$ref"]
    check_schema = schema["$defs"][checks_ref.rsplit("/", 1)[-1]]
    assert set(check_schema["properties"]) == {"name", "passed", "value", "required"}


def test_pipeline_plugin_chunk_report_endpoint_rejects_input_path_escape(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test

    plugin_root = tmp_path / "plugins"
    plugin_dir, sample_path = _write_api_report_plugin(plugin_root)
    run_pipeline_plugin_test(plugin_dir, input_path=sample_path, stages=["governance", "chunk", "kg"])
    client = _client(monkeypatch, plugin_root)

    res = client.post(
        "/api/v1/pipeline/plugins/chunk-report",
        json={
            "plugin_ref": "plugin:demo-report-api@1.0.0:chunk",
            "input_path": "../outside.json",
        },
    )

    assert res.status_code == 400
    assert "input_path must stay inside the plugin directory" in res.json()["detail"]
