from __future__ import annotations

import json
from pathlib import Path


def _write_release_plugin(tmp_path: Path, *, empty_chunks: bool = False) -> tuple[Path, Path]:
    plugin_dir = tmp_path / "plugins" / "demo-release-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "mimirq-plugin.json").write_text(
        json.dumps(
            {
                "id": "demo-release-plugin",
                "version": "1.0.0",
                "name": "Demo Release Plugin",
                "description": "Neutral plugin used by generic release gate tests",
                "status": "published",
                "entry": {
                    "governance": "plugin.py:govern_documents",
                    "chunk": "plugin.py:chunk_documents",
                    "kg": "plugin.py:build_kg_events",
                },
                "metadata_schema": "metadata_schema.json",
                "retrieval_text_schema": "retrieval_text_schema.json",
                "retrieval_policy": "retrieval_policy.json",
                "golden_rules": "golden_rules.json",
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
                        "name": "business_type",
                        "type": "string",
                        "required": True,
                        "stages": ["governance", "chunk"],
                        "filterable": True,
                        "display": True,
                        "evaluable": True,
                    },
                    {
                        "name": "record_name",
                        "type": "string",
                        "required": True,
                        "stages": ["governance", "chunk"],
                        "filterable": True,
                        "display": True,
                        "evaluable": True,
                    },
                    {
                        "name": "section_label",
                        "type": "string",
                        "stages": ["governance", "chunk"],
                        "filterable": True,
                        "display": True,
                        "evaluable": True,
                    },
                    {
                        "name": "chunk_kind",
                        "type": "string",
                        "required": True,
                        "stages": ["chunk"],
                        "filterable": True,
                        "display": True,
                        "evaluable": True,
                    },
                ],
                "record_identity": ["business_type", "record_name"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {
                    "chunk": {
                        "fields": [
                            {"metadata": "business_type", "label": "Business type"},
                            {"metadata": "record_name", "label": "Record"},
                            {"content": True, "label": "Evidence"},
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "retrieval_policy.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_policy.v1",
                "query_expansion_fields": ["record_name"],
                "query_expansion_values": [
                    {"metadata": "chunk_kind", "value": "demo_full", "terms": ["full record"]},
                ],
                "filter_fields": ["business_type", "section_label"],
                "boost_fields": [
                    {"metadata": "record_name", "weight": 1.5, "match": "exact"},
                ],
                "anchor_fields": [
                    {"metadata": "record_name", "weight": 2.0, "aliases": {"Alpha license": ["alpha"]}},
                ],
                "rerank_features": ["record_name", "chunk_kind"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "golden_rules.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.golden_rules.v1",
                "expected_metadata": ["record_name", "chunk_kind"],
                "answer_key_point_fields": ["record_name"],
                "template_selector_fields": ["chunk_kind"],
                "tag_fields": ["business_type", "chunk_kind"],
                "query_templates": {"demo_full": ["How do I handle {record_name}?"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chunk_body = "    return []" if empty_chunks else (
        "    return [\n"
        "        Document(\n"
        "            page_content=doc.page_content,\n"
        "            metadata={**dict(doc.metadata or {}), 'chunk_kind': 'demo_full'},\n"
        "        )\n"
        "        for doc in documents\n"
        "    ]"
    )
    (plugin_dir / "plugin.py").write_text(
        f"""
from langchain_core.documents import Document


def _title(text, fallback):
    for line in str(text or "").splitlines():
        if line.startswith("Title:"):
            return line.split(":", 1)[1].strip()
    return fallback


def govern_documents(documents, params=None, context=None):
    out = []
    for doc in documents:
        for index, raw in enumerate(str(doc.page_content or "").split("--item--")):
            text = raw.strip()
            if not text:
                continue
            out.append(
                Document(
                    page_content=text,
                    metadata={{
                        "business_type": "demo",
                        "record_name": _title(text, f"record-{{index + 1}}"),
                        "section_label": "demo-section",
                    }},
                )
            )
    return out


def chunk_documents(documents, params=None, context=None):
{chunk_body}


def build_kg_events(documents, params=None, context=None):
    return [
        {{
            "title": f"Demo graph: {{doc.metadata.get('record_name')}}",
            "summary": str(doc.page_content or "")[:80],
            "content": str(doc.page_content or ""),
            "extra_data": {{"section_label": doc.metadata.get("section_label")}},
            "entities": [
                {{"name": doc.metadata.get("record_name") or "record", "type": "DemoRecord", "role": "subject"}}
            ],
        }}
        for doc in documents
    ]
""".strip(),
        encoding="utf-8",
    )
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "page_content": (
                            "Title: Alpha license\n"
                            "Answer: TOP SECRET RAW SENTINEL should not appear in release gate.\n"
                            "--item--\n"
                            "Title: Beta filing\n"
                            "Answer: Submit the filing package."
                        ),
                        "metadata": {"source": "sample.txt"},
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return plugin_dir, sample_path


def test_plugin_release_gate_runs_generic_checks_and_hides_raw_chunk_examples(tmp_path: Path) -> None:
    from app.rag.pipeline_plugins.registry import PLUGIN_TEST_REPORT_FILENAME
    from scripts.plugin_release_gate import build_plugin_release_gate_report

    plugin_dir, sample_path = _write_release_plugin(tmp_path)

    report = build_plugin_release_gate_report(plugin_dir, sample_path=sample_path)

    assert report["schema"] == "mimirq.plugin_release_gate.v1"
    assert report["passed"] is True
    assert report["plugin"]["id"] == "demo-release-plugin"
    assert report["plugin"]["version"] == "1.0.0"
    assert report["plugin"]["package_hash"]
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["manifest_contracts_valid"]["passed"] is True
    assert checks["local_stage_test_passed"]["passed"] is True
    assert checks["local_test_report_current"]["passed"] is True
    assert checks["chunk_report_ready"]["passed"] is True
    assert checks["golden_draft_available"]["passed"] is True
    assert report["local_test"]["golden_draft"]["items_total"] == 2
    assert report["chunk_report"] == {
        "summary": {
            "input_documents": 1,
            "governed_records": 2,
            "chunks": 2,
            "kg_events": 2,
            "sections": 1,
        },
        "readiness": report["chunk_report"]["readiness"],
    }
    assert report["chunk_report"]["readiness"]["status"] == "passed"
    assert "sections" not in report["chunk_report"]
    assert (plugin_dir / PLUGIN_TEST_REPORT_FILENAME).is_file()
    assert "TOP SECRET RAW SENTINEL" not in json.dumps(report, ensure_ascii=False)


def test_plugin_release_gate_fails_when_required_chunk_stage_emits_no_chunks(tmp_path: Path) -> None:
    from scripts.plugin_release_gate import build_plugin_release_gate_report

    plugin_dir, sample_path = _write_release_plugin(tmp_path, empty_chunks=True)

    report = build_plugin_release_gate_report(plugin_dir, sample_path=sample_path)

    assert report["passed"] is False
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["chunk_report_ready"]["passed"] is False
    assert checks["chunk_report_ready"]["details"] == {
        "readiness_status": "failed",
        "failed_readiness_checks": ["chunks_present", "kg_events_present"],
    }
    assert checks["local_test_report_current"]["passed"] is False
    readiness_checks = {check["name"]: check for check in report["chunk_report"]["readiness"]["checks"]}
    assert readiness_checks["chunks_present"]["passed"] is False
