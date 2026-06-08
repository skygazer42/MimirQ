from __future__ import annotations

import json
from pathlib import Path


def _write_report_plugin(tmp_path: Path) -> tuple[Path, Path]:
    plugin_dir = tmp_path / "report-plugin"
    plugin_dir.mkdir()
    (plugin_dir / "mimirq-plugin.json").write_text(
        json.dumps(
            {
                "id": "demo-report-plugin",
                "version": "1.0.0",
                "name": "Demo Report Plugin",
                "description": "Neutral plugin used by generic report tests",
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
        for index, raw in enumerate(str(doc.page_content or "").split("--item--")):
            text = raw.strip()
            if not text:
                continue
            section = "alpha" if index == 0 else "beta"
            out.append(
                Document(
                    page_content=text,
                    metadata={
                        "section_label": section,
                        "record_label": text.splitlines()[0].strip(),
                    },
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
            "title": f"Record graph: {doc.metadata.get('record_label')}",
            "summary": str(doc.page_content or "")[:80],
            "content": str(doc.page_content or ""),
            "extra_data": {"section_label": doc.metadata.get("section_label")},
            "entities": [
                {"name": doc.metadata.get("record_label") or "record", "type": "Record", "role": "subject"}
            ],
        }
        for doc in documents
    ]
""".strip(),
        encoding="utf-8",
    )
    input_path = tmp_path / "sample.json"
    input_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "page_content": "Alpha access\nAnswer: Activate the account.\n--item--\nBeta renewal\nAnswer: Renew the account.",
                        "metadata": {"source": "sample.txt", "_indexed_metadata": {"leak": "no"}},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return plugin_dir, input_path


def test_generic_plugin_chunk_report_runs_stages_and_hides_platform_metadata_views(tmp_path: Path) -> None:
    from app.rag.pipeline_plugins.reports import build_pipeline_plugin_chunk_report

    plugin_dir, input_path = _write_report_plugin(tmp_path)

    report = build_pipeline_plugin_chunk_report(
        plugin_dir,
        input_path=input_path,
        section_metadata_keys=("section_label",),
        title_metadata_keys=("record_label",),
        metadata_highlight_keys=("section_label", "record_label", "answer_kind"),
        max_examples_per_section=1,
        preview_chars=48,
    )

    assert report["schema"] == "mimirq.pipeline_plugin_chunk_report.v1"
    assert report["passed"] is True
    assert report["plugin"]["id"] == "demo-report-plugin"
    assert report["summary"] == {
        "input_documents": 1,
        "governed_records": 2,
        "chunks": 2,
        "kg_events": 2,
        "sections": 2,
    }
    assert report["readiness"]["status"] == "passed"
    readiness_checks = {check["name"]: check for check in report["readiness"]["checks"]}
    assert readiness_checks["input_documents_present"] == {
        "name": "input_documents_present",
        "passed": True,
        "value": 1,
        "required": True,
    }
    assert readiness_checks["governed_records_present"]["value"] == 2
    assert readiness_checks["chunks_present"]["value"] == 2
    assert readiness_checks["metadata_fields_present"]["passed"] is True
    assert readiness_checks["metadata_fields_present"]["value"] > 0
    assert readiness_checks["kg_events_present"]["value"] == 2

    sections = {section["knowledge_section"]: section for section in report["sections"]}
    assert sorted(sections) == ["alpha", "beta"]
    alpha = sections["alpha"]
    assert alpha["governed_records"] == 1
    assert alpha["chunks"] == 1
    assert alpha["kg_events"] == 1
    assert alpha["chunk_kinds"] == {"demo_full": 1}
    assert "Record" in alpha["kg_entity_types"]
    assert "section_label" in alpha["metadata_fields"]
    assert "record_label" in alpha["metadata_fields"]
    assert "_indexed_metadata" not in alpha["metadata_fields"]
    assert "_display_metadata" not in alpha["metadata_fields"]
    assert "_evaluable_metadata" not in alpha["metadata_fields"]
    assert alpha["examples"][0]["title"] == "Alpha access"
    assert alpha["examples"][0]["metadata_focus"] == {
        "section_label": "alpha",
        "record_label": "Alpha access",
        "answer_kind": "full_record",
    }
    assert "_indexed_metadata" not in alpha["examples"][0]["metadata_focus"]


def test_generic_plugin_chunk_report_fails_when_chunk_metadata_contract_is_violated(tmp_path: Path) -> None:
    from app.rag.pipeline_plugins.reports import build_pipeline_plugin_chunk_report

    plugin_dir, input_path = _write_report_plugin(tmp_path)
    metadata_schema_path = plugin_dir / "metadata_schema.json"
    metadata_schema = json.loads(metadata_schema_path.read_text(encoding="utf-8"))
    metadata_schema["fields"].append(
        {
            "name": "answer_detail",
            "type": "string",
            "required": True,
            "stages": ["chunk"],
            "filterable": True,
            "display": True,
            "evaluable": True,
        }
    )
    metadata_schema_path.write_text(json.dumps(metadata_schema, ensure_ascii=False), encoding="utf-8")

    report = build_pipeline_plugin_chunk_report(
        plugin_dir,
        input_path=input_path,
        section_metadata_keys=("section_label",),
        title_metadata_keys=("record_label",),
    )

    assert report["passed"] is False
    assert report["readiness"]["status"] == "failed"
    readiness_checks = {check["name"]: check for check in report["readiness"]["checks"]}
    assert readiness_checks["governance_metadata_contract_valid"]["passed"] is True
    assert readiness_checks["chunk_metadata_contract_valid"]["passed"] is False
    assert readiness_checks["chunk_metadata_contract_valid"]["value"] == 2
    assert readiness_checks["chunk_metadata_contract_valid"]["errors"] == [
        {"reason": "plugin metadata contract failed for answer_detail: required"}
    ]
