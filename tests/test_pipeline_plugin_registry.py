from __future__ import annotations

import concurrent.futures
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.documents import Document


def _write_demo_plugin(
    plugin_dir: Path,
    *,
    suffix: str = "v1",
    include_contracts: bool = False,
    include_kg: bool = False,
    include_processing_templates: bool = False,
    include_retrieval_policy: bool = False,
    omit_required_metadata: bool = False,
    suggested_pipeline_patch: dict | None = None,
) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": "demo-service",
        "version": "1.0.0",
        "name": "Demo Service Plugin",
        "description": "Demo governance/chunk plugin",
        "status": "published",
        "entry": {
            "governance": "plugin.py:govern_documents",
            "chunk": "plugin.py:chunk_documents",
        },
    }
    if include_kg:
        manifest["entry"]["kg"] = "plugin.py:build_kg_events"
    if include_contracts:
        manifest.update(
            {
                "metadata_schema": "metadata_schema.json",
                "retrieval_text_schema": "retrieval_text_schema.json",
                "golden_rules": "golden_rules.json",
            }
        )
    if include_processing_templates:
        manifest["processing_templates"] = "processing_templates.json"
    if include_retrieval_policy:
        manifest["retrieval_policy"] = "retrieval_policy.json"
    if suggested_pipeline_patch is not None:
        manifest["suggested_pipeline_patch"] = suggested_pipeline_patch
    (plugin_dir / "mimirq-plugin.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    if include_contracts:
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
                            "max_length": 80,
                        },
                        {
                            "name": "chunk_kind",
                            "type": "string",
                            "required": True,
                            "stages": ["chunk"],
                            "filterable": True,
                            "display": True,
                            "evaluable": True,
                            "max_length": 80,
                        },
                    ],
                    "record_identity": ["business_type"],
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
                                {"metadata": "business_type", "label": "业务类型"},
                                {"metadata": "chunk_kind", "label": "切块类型"},
                                {"content": True, "label": "内容"},
                            ]
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (plugin_dir / "golden_rules.json").write_text(
            json.dumps(
                {
                    "schema": "mimirq.golden_rules.v1",
                    "expected_metadata": ["business_type", "chunk_kind"],
                    "template_selector_fields": ["business_type"],
                    "tag_fields": ["business_type", "chunk_kind"],
                    "query_templates": {"demo": ["{business_type}业务怎么处理？"]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    if include_retrieval_policy:
        (plugin_dir / "retrieval_policy.json").write_text(
            json.dumps(
                {
                    "schema": "mimirq.retrieval_policy.v1",
                    "query_expansion_fields": ["business_type"],
                    "query_expansion_values": [
                        {"metadata": "chunk_kind", "value": "demo", "terms": ["demo steps"]},
                    ],
                    "filter_fields": ["business_type"],
                    "boost_fields": [
                        {"metadata": "chunk_kind", "weight": 1.4, "match": "exact"},
                    ],
                    "anchor_fields": [
                        {
                            "metadata": "business_type",
                            "weight": 2.0,
                            "aliases": {"demo": ["demo", "demo business"]},
                        }
                    ],
                    "rerank_features": ["business_type", "chunk_kind"],
                    "fallback": {
                        "enabled": True,
                        "expand_top_k_multiplier": 2,
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from langchain_core.documents import Document",
                "",
                "def govern_documents(documents, params=None, context=None):",
                "    out = []",
                "    for doc in documents:",
                "        meta = dict(doc.metadata or {})",
                *([] if omit_required_metadata else ["        meta.setdefault('business_type', 'demo')"]),
                f"        out.append(Document(page_content=(doc.page_content + '::{suffix}'), metadata=meta))",
                "    return out",
                "",
                "def chunk_documents(documents, params=None, context=None):",
                "    return [Document(page_content=doc.page_content, metadata={**dict(doc.metadata or {}), 'chunk_kind': 'demo'}) for doc in documents]",
                "",
                "def build_kg_events(documents, params=None, context=None):",
                "    return [{'title': 'Demo KG', 'summary': doc.page_content, 'content': doc.page_content, 'entities': [{'name': 'demo', 'type': 'business'}]} for doc in documents]",
                "",
            ]
        ),
        encoding="utf-8",
    )
    if include_processing_templates:
        (plugin_dir / "processing_templates.json").write_text(
            json.dumps(
                {
                    "schema": "mimirq.pipeline_plugin_processing_templates.v1",
                    "plugin_id": "demo-service",
                    "version": "1.0.0",
                    "description": "Demo plugin-owned processing templates",
                    "templates": [
                        {
                            "key": "demo_governance_template",
                            "name": "Demo governance template",
                            "stage": "governance",
                            "implemented_by": "plugin.py:govern_documents",
                            "related_implementations": ["plugin.py:chunk_documents"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def test_published_plugin_without_local_test_report_is_not_executable(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import (
        PipelinePluginRegistryError,
        list_pipeline_plugins,
        resolve_registered_plugin_callable,
    )

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)

    plugins = list_pipeline_plugins([tmp_path / "plugins"])

    assert len(plugins) == 1
    assert plugins[0].id == "demo-service"
    assert plugins[0].published is True
    assert plugins[0].executable is False
    assert plugins[0].test_status == "missing"

    with pytest.raises(PipelinePluginRegistryError, match="local test report"):
        resolve_registered_plugin_callable(
            "plugin:demo-service@1.0.0:governance",
            directories=[tmp_path / "plugins"],
        )


def test_local_runner_report_allows_registered_plugin_execution(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test
    from app.rag.pipeline_plugins.registry import (
        list_pipeline_plugins,
        resolve_registered_plugin_callable,
    )

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(
        json.dumps(
            [{"page_content": "hello", "metadata": {"source": "sample.txt"}}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_pipeline_plugin_test(plugin_dir, input_path=sample_path, stages=["governance", "chunk"])

    assert report["passed"] is True
    assert report["stages"]["governance"]["output_count"] == 1
    assert report["stages"]["chunk"]["output_count"] == 1

    plugins = list_pipeline_plugins([tmp_path / "plugins"])
    assert plugins[0].executable is True
    assert plugins[0].refs["governance"] == "plugin:demo-service@1.0.0:governance"

    func = resolve_registered_plugin_callable(
        "plugin:demo-service@1.0.0:governance",
        directories=[tmp_path / "plugins"],
    )
    result = func([Document(page_content="live", metadata={})], {}, {})

    assert result[0].page_content == "live::v1"


def test_registry_supports_optional_kg_plugin_stage(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test
    from app.rag.pipeline_plugins.registry import (
        list_pipeline_plugins,
        resolve_registered_plugin_callable,
    )

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_kg=True)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")

    report = run_pipeline_plugin_test(plugin_dir, input_path=sample_path, stages=["governance", "chunk", "kg"])

    plugins = list_pipeline_plugins([tmp_path / "plugins"])
    assert report["passed"] is True
    assert report["stages"]["kg"]["output_count"] == 1
    assert plugins[0].refs["kg"] == "plugin:demo-service@1.0.0:kg"
    assert plugins[0].test_report["stages"]["kg"]["metadata_ok"] is True

    func = resolve_registered_plugin_callable(
        "plugin:demo-service@1.0.0:kg",
        directories=[tmp_path / "plugins"],
    )
    assert func([Document(page_content="live", metadata={})], {}, {})[0]["title"] == "Demo KG"


def test_local_runner_reports_reserved_kg_metadata_view_failure(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_kg=True)
    plugin_path = plugin_dir / "plugin.py"
    plugin_source = plugin_path.read_text(encoding="utf-8")
    plugin_path.write_text(
        plugin_source.replace(
            "'entities': [{'name': 'demo', 'type': 'business'}]",
            "'metadata': {'_indexed_metadata': {'record_key': 'demo'}}, "
            "'entities': [{'name': 'demo', 'type': 'business'}]",
        ),
        encoding="utf-8",
    )
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")

    report = run_pipeline_plugin_test(
        plugin_dir,
        input_path=sample_path,
        stages=["governance", "chunk", "kg"],
        write_report=False,
    )

    assert report["passed"] is False
    assert report["stages"]["kg"]["passed"] is False
    assert report["stages"]["kg"]["kg_validation"]["ok"] is False
    assert report["stages"]["kg"]["kg_validation"]["errors"] == [
        {"reason": "kg plugin metadata must not contain reserved platform metadata field '_indexed_metadata'"}
    ]


def test_local_runner_reports_reserved_document_metadata_view_failure(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    plugin_path = plugin_dir / "plugin.py"
    plugin_source = plugin_path.read_text(encoding="utf-8")
    plugin_path.write_text(
        plugin_source.replace(
            "        meta.setdefault('business_type', 'demo')",
            "        meta.setdefault('business_type', 'demo')\n"
            "        meta['_indexed_metadata'] = {'record_key': 'demo'}",
        ),
        encoding="utf-8",
    )
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")

    report = run_pipeline_plugin_test(
        plugin_dir,
        input_path=sample_path,
        stages=["governance"],
        write_report=False,
    )

    assert report["passed"] is False
    assert report["stages"]["governance"]["passed"] is False
    assert report["stages"]["governance"]["metadata_validation"]["ok"] is False
    assert report["stages"]["governance"]["metadata_validation"]["errors"] == [
        {"reason": "governance plugin metadata must not contain reserved platform metadata field '_indexed_metadata'"}
    ]


def test_local_runner_reports_unsupported_document_output_failure(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    plugin_path = plugin_dir / "plugin.py"
    plugin_path.write_text(
        plugin_path.read_text(encoding="utf-8").replace("    return out", "    return [object()]", 1),
        encoding="utf-8",
    )
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")

    report = run_pipeline_plugin_test(
        plugin_dir,
        input_path=sample_path,
        stages=["governance"],
        write_report=False,
    )

    assert report["passed"] is False
    assert report["stages"]["governance"]["passed"] is False
    assert report["stages"]["governance"]["metadata_validation"]["ok"] is False
    assert report["stages"]["governance"]["metadata_validation"]["errors"] == [
        {"reason": "python plugin returned unsupported item at index 0: object"}
    ]


def test_local_runner_reports_plugin_function_exception_failure(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    plugin_path = plugin_dir / "plugin.py"
    plugin_path.write_text(
        plugin_path.read_text(encoding="utf-8").replace(
            "def govern_documents(documents, params=None, context=None):",
            "def govern_documents(documents, params=None, context=None):\n    raise RuntimeError('demo governance failure')",
            1,
        ),
        encoding="utf-8",
    )
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")

    report = run_pipeline_plugin_test(
        plugin_dir,
        input_path=sample_path,
        stages=["governance"],
        write_report=False,
    )

    assert report["passed"] is False
    assert report["stages"]["governance"]["passed"] is False
    assert report["stages"]["governance"]["metadata_validation"]["ok"] is False
    assert report["stages"]["governance"]["metadata_validation"]["errors"] == [
        {"reason": "demo governance failure"}
    ]


def test_local_runner_executes_governance_before_chunk_and_validates_golden_draft(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "golden_rules.json").write_text(
        json.dumps(
                {
                    "schema": "mimirq.golden_rules.v1",
                    "expected_metadata": ["business_type", "chunk_kind"],
                    "template_selector_fields": ["business_type"],
                    "tag_fields": ["business_type", "chunk_kind"],
                    "query_templates": {"demo": ["{business_type}业务怎么处理？"]},
                },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")

    report = run_pipeline_plugin_test(
        plugin_dir,
        input_path=sample_path,
        stages=["governance", "chunk"],
        write_report=False,
    )

    assert report["passed"] is True
    assert report["stages"]["chunk"]["metadata_validation"]["ok"] is True
    assert report["golden_draft"]["passed"] is True
    assert report["golden_draft"]["items_total"] == 1
    assert report["golden_draft"]["sample_questions"] == ["demo业务怎么处理？"]


def test_pipeline_plugin_runner_exports_local_golden_draft_bundle(tmp_path: Path):
    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")
    out_path = tmp_path / "golden.json"
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_plugin_runner.py"

    res = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "golden-draft",
            str(plugin_dir),
            "--input",
            str(sample_path),
            "--dataset-id",
            "00000000-0000-0000-0000-000000000123",
            "--out",
            str(out_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert res.returncode == 0, res.stderr
    assert "SECRET_KEY is not configured" not in res.stderr
    bundle = json.loads(out_path.read_text(encoding="utf-8"))
    assert bundle["schema"] == "mimirq.regression_cases.v1"
    assert bundle["dataset_id"] == "00000000-0000-0000-0000-000000000123"
    assert bundle["review_only"] is True
    assert bundle["reference_source_mode"] == "local_sample_synthetic"
    assert bundle["items"][0]["question"] == "demo业务怎么处理？"
    assert bundle["items"][0]["extra"]["plugin_version"] == "1.0.0"
    assert bundle["items"][0]["extra"]["plugin_ref"] == "plugin:demo-service@1.0.0:chunk"
    assert bundle["items"][0]["extra"]["plugin_package_hash"]
    assert bundle["items"][0]["extra"]["expected_metadata"] == {"business_type": "demo", "chunk_kind": "demo"}
    assert bundle["items"][0]["extra"]["reference_source_mode"] == "local_sample_synthetic"


def test_pipeline_plugin_runner_golden_draft_can_validate_kg_stage(tmp_path: Path):
    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, include_kg=True)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")
    out_path = tmp_path / "golden.json"
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_plugin_runner.py"

    res = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "golden-draft",
            str(plugin_dir),
            "--input",
            str(sample_path),
            "--stage",
            "governance",
            "--stage",
            "chunk",
            "--stage",
            "kg",
            "--dataset-id",
            "00000000-0000-0000-0000-000000000123",
            "--out",
            str(out_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert res.returncode == 0, res.stderr
    bundle = json.loads(out_path.read_text(encoding="utf-8"))
    assert bundle["items"][0]["extra"]["plugin_ref"] == "plugin:demo-service@1.0.0:chunk"


def test_local_runner_golden_drafts_use_chunk_ref_only() -> None:
    text = Path("app/rag/pipeline_plugins/local_runner.py").read_text(encoding="utf-8")

    assert text.count('plugin_ref=descriptor.refs["chunk"]') == 2
    assert 'descriptor.refs.get("governance")' not in text


def test_registered_plugin_with_golden_rules_requires_golden_draft_test_report(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import (
        PLUGIN_TEST_REPORT_FILENAME,
        describe_plugin_dir,
        list_pipeline_plugins,
    )

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    (plugin_dir / PLUGIN_TEST_REPORT_FILENAME).write_text(
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
                        "output_count": 1,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                    "chunk": {
                        "passed": True,
                        "input_count": 1,
                        "output_count": 1,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plugins = list_pipeline_plugins([tmp_path / "plugins"])

    assert plugins[0].executable is False
    assert plugins[0].test_status == "golden_missing"


def test_changed_plugin_source_invalidates_local_test_report(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test
    from app.rag.pipeline_plugins.registry import (
        PipelinePluginRegistryError,
        list_pipeline_plugins,
        resolve_registered_plugin_callable,
    )

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")
    run_pipeline_plugin_test(plugin_dir, input_path=sample_path, stages=["governance"])

    _write_demo_plugin(plugin_dir, suffix="v2")

    plugins = list_pipeline_plugins([tmp_path / "plugins"])
    assert plugins[0].executable is False
    assert plugins[0].test_status == "stale"

    with pytest.raises(PipelinePluginRegistryError, match="stale"):
        resolve_registered_plugin_callable(
            "plugin:demo-service@1.0.0:governance",
            directories=[tmp_path / "plugins"],
        )


def test_mismatched_plugin_test_report_identity_is_not_executable(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import (
        PLUGIN_TEST_REPORT_FILENAME,
        describe_plugin_dir,
        list_pipeline_plugins,
    )

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    (plugin_dir / PLUGIN_TEST_REPORT_FILENAME).write_text(
        json.dumps(
            {
                "plugin_id": "other-plugin",
                "version": "9.9.9",
                "package_hash": descriptor.package_hash,
                "passed": True,
                "stages": {
                    "governance": {"passed": True},
                    "chunk": {"passed": True},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plugins = list_pipeline_plugins([tmp_path / "plugins"])

    assert plugins[0].executable is False
    assert plugins[0].test_status == "mismatch"


def test_plugin_test_report_with_failed_metadata_validation_is_not_executable(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import (
        PLUGIN_TEST_REPORT_FILENAME,
        describe_plugin_dir,
        list_pipeline_plugins,
    )

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    (plugin_dir / PLUGIN_TEST_REPORT_FILENAME).write_text(
        json.dumps(
            {
                "plugin_id": descriptor.id,
                "version": descriptor.version,
                "package_hash": descriptor.package_hash,
                "passed": True,
                "stages": {
                    "governance": {
                        "passed": True,
                        "metadata_validation": {"ok": False, "errors": [{"field": "business_type"}]},
                    },
                    "chunk": {
                        "passed": True,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                },
                "golden_draft": {"passed": True, "items_total": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plugins = list_pipeline_plugins([tmp_path / "plugins"])

    assert plugins[0].executable is False
    assert plugins[0].test_status == "failed"


def test_plugin_test_report_with_empty_stage_output_is_not_executable(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import (
        PLUGIN_TEST_REPORT_FILENAME,
        describe_plugin_dir,
        list_pipeline_plugins,
    )

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    (plugin_dir / PLUGIN_TEST_REPORT_FILENAME).write_text(
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
                        "output_count": 0,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                    "chunk": {
                        "passed": True,
                        "input_count": 1,
                        "output_count": 1,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plugins = list_pipeline_plugins([tmp_path / "plugins"])

    assert plugins[0].executable is False
    assert plugins[0].test_status == "failed"


def test_plugin_test_report_with_unknown_stage_is_not_executable(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import (
        PLUGIN_TEST_REPORT_FILENAME,
        describe_plugin_dir,
        list_pipeline_plugins,
    )

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    (plugin_dir / PLUGIN_TEST_REPORT_FILENAME).write_text(
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
                        "output_count": 1,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                    "chunk": {
                        "passed": True,
                        "input_count": 1,
                        "output_count": 1,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                    "business_enrichment": {
                        "passed": True,
                        "input_count": 1,
                        "output_count": 1,
                        "metadata_validation": {"ok": True, "errors": []},
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    plugins = list_pipeline_plugins([tmp_path / "plugins"])

    assert plugins[0].executable is False
    assert plugins[0].test_status == "failed"
    assert "business_enrichment" not in plugins[0].test_report["stages"]


def test_pipeline_plugins_endpoint_lists_registered_refs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.api.v1.pipeline import list_pipeline_plugins_endpoint
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")
    run_pipeline_plugin_test(plugin_dir, input_path=sample_path, stages=["governance", "chunk"])
    monkeypatch.setattr("app.rag.pipeline_plugins.registry.settings.PYTHON_PIPELINE_PLUGIN_DIRS", str(tmp_path / "plugins"))

    app = FastAPI()
    app.get("/api/v1/pipeline/plugins")(list_pipeline_plugins_endpoint)
    client = TestClient(app)

    res = client.get("/api/v1/pipeline/plugins")

    assert res.status_code == 200
    body = res.json()
    assert body["items"][0]["id"] == "demo-service"
    assert body["items"][0]["executable"] is True
    assert body["items"][0]["refs"]["governance"] == "plugin:demo-service@1.0.0:governance"
    assert body["items"][0]["package_hash"]
    assert body["items"][0]["test_report"]["plugin_id"] == "demo-service"
    assert body["items"][0]["test_report"]["version"] == "1.0.0"
    assert body["items"][0]["test_report"]["package_hash"] == body["items"][0]["package_hash"]
    assert body["items"][0]["test_report"]["tested_at"]
    assert body["items"][0]["test_report"]["stages"]["governance"]["passed"] is True
    assert body["items"][0]["test_report"]["stages"]["chunk"]["output_count"] == 1


def test_pipeline_plugin_manifest_suggested_patch_is_exposed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.api.v1.pipeline import list_pipeline_plugins_endpoint
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test
    from app.rag.pipeline_plugins.registry import describe_plugin_dir

    suggested_patch = {
        "governance_enabled": True,
        "chunk_python_params": {"demo_param": 1500},
        "kg_python_params": {"profile": "demo"},
        "persist_parsed_content": True,
    }
    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_kg=True, suggested_pipeline_patch=suggested_patch)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")
    run_pipeline_plugin_test(plugin_dir, input_path=sample_path, stages=["governance", "chunk", "kg"])
    monkeypatch.setattr("app.rag.pipeline_plugins.registry.settings.PYTHON_PIPELINE_PLUGIN_DIRS", str(tmp_path / "plugins"))

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    assert descriptor.suggested_pipeline_patch == suggested_patch

    app = FastAPI()
    app.get("/api/v1/pipeline/plugins")(list_pipeline_plugins_endpoint)
    client = TestClient(app)

    res = client.get("/api/v1/pipeline/plugins")

    assert res.status_code == 200
    body = res.json()
    assert body["items"][0]["suggested_pipeline_patch"] == suggested_patch
    assert "chunk_size" not in body["items"][0]["suggested_pipeline_patch"]
    assert "governance_python_plugin" not in body["items"][0]["suggested_pipeline_patch"]


def test_plugin_manifest_suggested_patch_rejects_params_without_matching_entry(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(
        plugin_dir,
        suggested_pipeline_patch={
            "kg_python_params": {"profile": "demo"},
        },
    )

    with pytest.raises(PipelinePluginRegistryError, match="suggested_pipeline_patch kg_python_params requires plugin entry stage kg"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_processing_templates_are_manifest_declared_and_exposed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from app.api.v1.pipeline import list_pipeline_plugins_endpoint
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test
    from app.rag.pipeline_plugins.registry import describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_processing_templates=True)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")
    run_pipeline_plugin_test(plugin_dir, input_path=sample_path, stages=["governance", "chunk"])
    monkeypatch.setattr("app.rag.pipeline_plugins.registry.settings.PYTHON_PIPELINE_PLUGIN_DIRS", str(tmp_path / "plugins"))

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    assert descriptor.processing_templates["schema"] == "mimirq.pipeline_plugin_processing_templates.v1"
    assert descriptor.processing_templates["templates"][0]["key"] == "demo_governance_template"

    app = FastAPI()
    app.get("/api/v1/pipeline/plugins")(list_pipeline_plugins_endpoint)
    client = TestClient(app)

    res = client.get("/api/v1/pipeline/plugins")

    assert res.status_code == 200
    item = res.json()["items"][0]
    assert item["processing_templates"]["plugin_id"] == "demo-service"
    assert item["processing_templates"]["templates"][0]["implemented_by"] == "plugin.py:govern_documents"


def test_pipeline_plugin_retrieval_policy_is_manifest_declared_and_summarized(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, include_retrieval_policy=True)

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)

    assert descriptor.retrieval_policy["schema"] == "mimirq.retrieval_policy.v1"
    assert descriptor.retrieval_policy["query_expansion_fields"] == ["business_type"]
    assert descriptor.retrieval_policy["filter_fields"] == ["business_type"]
    assert descriptor.contract_summary["retrieval_policy"] == {
        "schema": "mimirq.retrieval_policy.v1",
        "query_expansion_fields": ["business_type"],
        "query_expansion_value_fields": ["chunk_kind"],
        "filter_fields": ["business_type"],
        "boost_fields": ["chunk_kind"],
        "anchor_fields": ["business_type"],
        "rerank_features": ["business_type", "chunk_kind"],
        "question_intent_terms": [],
        "mixed_intent_leading_noise_terms": [],
        "mixed_intent_subject_terms": [],
        "service_anchor_noise_terms": [],
        "service_anchor_priority_terms": [],
        "metadata_anchor_preflight_block_terms": [],
        "service_anchor_query_rewrites": 0,
        "anchor_binding_fields": [],
        "anchor_binding_enabled": False,
        "fallback_enabled": True,
        "response_compaction_enabled": False,
        "response_hints_enabled": False,
    }


def test_pipeline_plugin_retrieval_policy_allows_response_hint_overlap_gate(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, include_retrieval_policy=True)
    (plugin_dir / "retrieval_policy.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_policy.v1",
                "question_anchor_bonus": 0.9,
                "response_hints": {
                    "structured_labels": ["业务类型", "别名"],
                    "groups": [
                        {
                            "name": "service_item",
                            "required_any_labels": ["业务类型"],
                            "hint_labels": ["业务类型"],
                            "query_gate": {
                                "content_labels": ["业务类型", "别名"],
                                "metadata": ["business_type"],
                                "min_chars": 4,
                                "min_common_chars": 3,
                            },
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)

    assert descriptor.retrieval_policy["question_anchor_bonus"] == 0.9
    gate = descriptor.retrieval_policy["response_hints"]["groups"][0]["query_gate"]
    assert gate["min_common_chars"] == 3


def test_pipeline_plugin_list_schema_accepts_retrieval_policy_anchor_fields(tmp_path: Path):
    from app.api.schemas.pipeline import PipelinePluginListResponse
    from app.rag.pipeline_plugins.registry import describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, include_retrieval_policy=True)

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)

    response = PipelinePluginListResponse.model_validate(
        {
            "items": [
                {
                    "id": descriptor.id,
                    "version": descriptor.version,
                    "name": descriptor.name,
                    "description": descriptor.description,
                    "published": descriptor.published,
                    "executable": descriptor.executable,
                    "test_status": descriptor.test_status,
                    "package_hash": descriptor.package_hash,
                    "stages": list(descriptor.entries),
                    "refs": descriptor.refs,
                    "contract": descriptor.contract_summary,
                }
            ],
            "errors": [],
        }
    )

    assert response.items[0].contract.retrieval_policy.anchor_fields == ["business_type"]


def test_pipeline_plugin_retrieval_policy_rejects_undeclared_metadata_fields(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, include_retrieval_policy=True)
    policy_path = plugin_dir / "retrieval_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["query_expansion_fields"] = ["missing_business_alias"]
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="retrieval_policy.query_expansion_fields references undeclared metadata fields: missing_business_alias",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_retrieval_policy_rejects_undeclared_query_expansion_value_fields(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, include_retrieval_policy=True)
    policy_path = plugin_dir / "retrieval_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["query_expansion_values"] = [{"metadata": "missing_segment", "value": "demo", "terms": ["demo"]}]
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="retrieval_policy.query_expansion_values references undeclared metadata fields: missing_segment",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_retrieval_policy_rejects_undeclared_anchor_fields(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, include_retrieval_policy=True)
    policy_path = plugin_dir / "retrieval_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["anchor_fields"] = [{"metadata": "missing_region", "aliases": {"north": ["north"]}}]
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="retrieval_policy.anchor_fields references undeclared metadata fields: missing_region",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_retrieval_policy_rejects_non_chunk_stage_fields(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, include_retrieval_policy=True)
    schema_path = plugin_dir / "metadata_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["fields"].append(
        {
            "name": "governance_note",
            "type": "string",
            "required": False,
            "stages": ["governance"],
            "filterable": True,
            "display": True,
            "evaluable": True,
        }
    )
    schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")

    policy_path = plugin_dir / "retrieval_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["boost_fields"] = [{"metadata": "governance_note", "weight": 1.0, "match": "contains"}]
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="retrieval_policy.boost_fields references metadata fields not available at chunk stage: governance_note",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_retrieval_policy_rejects_non_chunk_query_expansion_value_fields(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, include_retrieval_policy=True)
    schema_path = plugin_dir / "metadata_schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["fields"].append(
        {
            "name": "governance_note",
            "type": "string",
            "required": False,
            "stages": ["governance"],
            "filterable": True,
            "display": True,
            "evaluable": True,
        }
    )
    schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")

    policy_path = plugin_dir / "retrieval_policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["query_expansion_values"] = [{"metadata": "governance_note", "value": "demo", "terms": ["demo"]}]
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match=(
            "retrieval_policy.query_expansion_values references metadata fields "
            "not available at chunk stage: governance_note"
        ),
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_processing_templates_reject_builtin_template_key_collision(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_processing_templates=True)
    templates_path = plugin_dir / "processing_templates.json"
    payload = json.loads(templates_path.read_text(encoding="utf-8"))
    payload["templates"][0]["key"] = "cn_number_normalize"
    templates_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="processing_templates.templates\\[0\\].key collides"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_processing_templates_reject_platform_implemented_by_ref(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_processing_templates=True)
    templates_path = plugin_dir / "processing_templates.json"
    payload = json.loads(templates_path.read_text(encoding="utf-8"))
    payload["templates"][0]["implemented_by"] = "app.services.pipeline_config:resolve_pipeline_options"
    templates_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="processing_templates.templates\\[0\\].implemented_by must not use platform package names",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_processing_templates_reject_platform_related_implementation_ref(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_processing_templates=True)
    templates_path = plugin_dir / "processing_templates.json"
    payload = json.loads(templates_path.read_text(encoding="utf-8"))
    payload["templates"][0]["related_implementations"] = ["scripts/platform_template.py:govern_documents"]
    templates_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="processing_templates.templates\\[0\\].related_implementations\\[0\\] must not use platform package names",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_processing_templates_reject_missing_implemented_by_symbol(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_processing_templates=True)
    templates_path = plugin_dir / "processing_templates.json"
    payload = json.loads(templates_path.read_text(encoding="utf-8"))
    payload["templates"][0]["implemented_by"] = "plugin.py:missing_governance_symbol"
    templates_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="processing_templates.templates\\[0\\].implemented_by must reference an existing plugin-local symbol",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_processing_templates_reject_missing_related_implementation_symbol(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_processing_templates=True)
    templates_path = plugin_dir / "processing_templates.json"
    payload = json.loads(templates_path.read_text(encoding="utf-8"))
    payload["templates"][0]["related_implementations"] = ["plugin.py:missing_chunk_symbol"]
    templates_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match=(
            "processing_templates.templates\\[0\\].related_implementations\\[0\\] "
            "must reference an existing plugin-local symbol"
        ),
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_manifest_suggested_patch_rejects_unknown_business_keys(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(
        plugin_dir,
        suggested_pipeline_patch={
            "governance_enabled": True,
            "business_only_window_chars": 1500,
        },
    )

    with pytest.raises(PipelinePluginRegistryError, match="suggested_pipeline_patch contains unknown keys"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


@pytest.mark.parametrize("params_key", ["governance_python_params", "chunk_python_params", "kg_python_params"])
def test_pipeline_plugin_manifest_suggested_patch_rejects_nested_python_params(
    tmp_path: Path,
    params_key: str,
):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(
        plugin_dir,
        include_kg=params_key == "kg_python_params",
        suggested_pipeline_patch={
            params_key: {
                "business_profile": {"mode": "nested"},
            },
        },
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin manifest field 'suggested_pipeline_patch' is invalid"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


@pytest.mark.parametrize(
    ("patch_key", "patch_value"),
    [
        ("chunk_size", 1600),
        ("chunk_overlap", 160),
        ("chunk_merge_small_min_chars", 200),
        ("chunk_strategy_params", {"separator": "\\n\\n"}),
        ("governance_remove_noise_lines", True),
        ("governance_rule_packs", ["pdf_watermark"]),
        ("governance_regex_rules", [{"pattern": "demo", "replacement": ""}]),
    ],
)
def test_pipeline_plugin_manifest_suggested_patch_rejects_platform_strategy_knobs(
    tmp_path: Path,
    patch_key: str,
    patch_value: object,
):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(
        plugin_dir,
        suggested_pipeline_patch={
            "governance_enabled": True,
            patch_key: patch_value,
        },
    )

    with pytest.raises(PipelinePluginRegistryError, match="suggested_pipeline_patch must not set platform strategy fields"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


@pytest.mark.parametrize(
    ("patch_key", "patch_value"),
    [
        ("kg_enabled", True),
        ("parse_cache_enabled", True),
        ("embedding_context_prefix_enabled", True),
        ("persist_parsed_content_max_chars", 200_000),
    ],
)
def test_pipeline_plugin_manifest_suggested_patch_rejects_non_allowlisted_platform_options(
    tmp_path: Path,
    patch_key: str,
    patch_value: object,
):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(
        plugin_dir,
        suggested_pipeline_patch={
            "governance_enabled": True,
            patch_key: patch_value,
        },
    )

    with pytest.raises(PipelinePluginRegistryError, match="suggested_pipeline_patch may only set plugin suggested fields"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_manifest_rejects_unknown_top_level_business_keys(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["business_type"] = "demo_case"
    manifest["district"] = "demo_region"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="plugin manifest contains unknown top-level fields: business_type, district",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_manifest_suggested_patch_rejects_plugin_activation_refs(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(
        plugin_dir,
        suggested_pipeline_patch={
            "governance_enabled": True,
            "governance_python_plugin": "plugin:other-service@1.0.0:governance",
            "chunk_python_plugin": "plugin:other-service@1.0.0:chunk",
            "kg_python_plugin": "plugin:other-service@1.0.0:kg",
        },
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="chunk_python_plugin, governance_python_plugin, kg_python_plugin",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_manifest_rejects_empty_entry_function_name(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"]["chunk"] = "plugin.py:"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="plugin entry for chunk must include a callable function name",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugin_manifest_rejects_non_string_entry_target(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"]["chunk"] = 123
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="plugin entry for chunk must be a string module target",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_pipeline_plugins_endpoint_lists_valid_plugins_when_one_plugin_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    from app.api.v1.pipeline import list_pipeline_plugins_endpoint

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    invalid_dir = tmp_path / "plugins" / "broken"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "mimirq-plugin.json").write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr("app.rag.pipeline_plugins.registry.settings.PYTHON_PIPELINE_PLUGIN_DIRS", str(tmp_path / "plugins"))

    app = FastAPI()
    app.get("/api/v1/pipeline/plugins")(list_pipeline_plugins_endpoint)
    client = TestClient(app)

    res = client.get("/api/v1/pipeline/plugins")

    assert res.status_code == 200
    body = res.json()
    assert [item["id"] for item in body["items"]] == ["demo-service"]
    assert body["errors"][0]["plugin_dir"] == "broken"
    assert body["errors"][0]["manifest_path"] == "broken/mimirq-plugin.json"
    assert str(tmp_path) not in body["errors"][0]["plugin_dir"]
    assert str(tmp_path) not in body["errors"][0]["manifest_path"]
    assert "Expecting property name" in body["errors"][0]["error"]


def test_pipeline_plugins_endpoint_has_openapi_response_model():
    from app.api.v1.pipeline import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/pipeline")

    schema = app.openapi()["paths"]["/api/v1/pipeline/plugins"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    ref = str(schema.get("$ref") or "")

    assert ref.endswith("/PipelinePluginListResponse")
    plugin_schema = app.openapi()["components"]["schemas"]["PipelinePluginListResponse"]
    assert sorted(plugin_schema["properties"].keys()) == ["errors", "items"]


def test_pipeline_plugins_endpoint_openapi_types_processing_templates_contract():
    from app.api.v1.pipeline import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/pipeline")
    components = app.openapi()["components"]["schemas"]

    item_schema = components["PipelinePluginItem"]
    suggested_patch_ref = item_schema["properties"]["suggested_pipeline_patch"].get("$ref", "")
    assert suggested_patch_ref.endswith("/PipelinePluginSuggestedPatch")
    suggested_patch_schema = components["PipelinePluginSuggestedPatch"]
    assert set(suggested_patch_schema["properties"].keys()) == {
        "governance_enabled",
        "governance_python_params",
        "chunk_python_params",
        "kg_python_params",
        "persist_parsed_content",
    }
    assert "chunk_size" not in suggested_patch_schema["properties"]
    assert "chunk_strategy_params" not in suggested_patch_schema["properties"]
    assert "governance_python_plugin" not in suggested_patch_schema["properties"]
    assert suggested_patch_schema["additionalProperties"] is False
    primitive_types = {"string", "integer", "number", "boolean"}
    for params_key in ("governance_python_params", "chunk_python_params", "kg_python_params"):
        params_property = suggested_patch_schema["properties"][params_key]
        object_schema = next(item for item in params_property["anyOf"] if item.get("type") == "object")
        additional_properties = object_schema["additionalProperties"]
        assert isinstance(additional_properties, dict)
        allowed_value_types = {item.get("type") for item in additional_properties["anyOf"] if item.get("type")}
        assert primitive_types.issubset(allowed_value_types)
        assert "object" not in allowed_value_types
        assert "array" not in allowed_value_types
    assert item_schema["properties"]["stages"]["items"]["enum"] == ["governance", "chunk", "kg"]
    refs_ref = item_schema["properties"]["refs"].get("$ref", "")
    assert refs_ref.endswith("/PipelinePluginRefs")
    refs_schema = components["PipelinePluginRefs"]
    assert set(refs_schema["properties"].keys()) == {"governance", "chunk", "kg"}
    assert refs_schema["additionalProperties"] is False

    processing_ref = item_schema["properties"]["processing_templates"].get("$ref", "")
    assert processing_ref.endswith("/PipelinePluginProcessingTemplates")

    templates_schema = components["PipelinePluginProcessingTemplates"]
    assert set(templates_schema["properties"].keys()) == {
        "schema",
        "plugin_id",
        "version",
        "description",
        "templates",
    }
    assert templates_schema["additionalProperties"] is False
    template_items = templates_schema["properties"]["templates"]["items"]
    assert template_items["$ref"].endswith("/PipelinePluginProcessingTemplate")

    template_schema = components["PipelinePluginProcessingTemplate"]
    assert set(template_schema["properties"].keys()) == {
        "key",
        "name",
        "description",
        "stage",
        "implemented_by",
        "related_implementations",
    }
    assert template_schema["additionalProperties"] is False
    assert template_schema["properties"]["stage"].get("enum") == ["governance", "chunk", "kg"]


def test_pipeline_plugins_endpoint_openapi_types_summary_contracts_are_closed():
    from app.api.v1.pipeline import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/pipeline")
    components = app.openapi()["components"]["schemas"]

    for schema_name in (
        "PipelinePluginTestStageSummary",
        "PipelinePluginGoldenTestSummary",
        "PipelinePluginTestReportSummary",
        "PipelinePluginMetadataContractSummary",
        "PipelinePluginRetrievalTextContractSummary",
        "PipelinePluginGoldenContractSummary",
        "PipelinePluginContractSummary",
        "PipelinePluginListError",
        "PipelinePluginListResponse",
    ):
        assert components[schema_name]["additionalProperties"] is False, schema_name


def test_plugin_descriptor_loads_contract_files_and_includes_them_in_package_hash(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    before_hash = descriptor.package_hash

    assert descriptor.metadata_schema["schema"] == "mimirq.metadata_schema.v1"
    assert descriptor.contract_summary["metadata"]["fields"] == ["business_type", "chunk_kind"]
    assert descriptor.contract_summary["metadata"]["required_fields"] == ["business_type", "chunk_kind"]
    assert descriptor.contract_summary["metadata"]["record_identity_fields"] == ["business_type"]
    assert descriptor.retrieval_text_schema["schema"] == "mimirq.retrieval_text_schema.v1"
    assert descriptor.golden_rules["schema"] == "mimirq.golden_rules.v1"

    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
                {
                    "schema": "mimirq.metadata_schema.v1",
                    "fields": [
                        {"name": "business_type", "type": "string", "required": True, "evaluable": True},
                        {"name": "chunk_kind", "type": "string", "required": True, "max_length": 81, "evaluable": True},
                    ],
                }
            ),
            encoding="utf-8",
    )

    assert describe_plugin_dir(plugin_dir, require_test_report=False).package_hash != before_hash


def test_plugin_descriptor_rejects_empty_declared_contract_path(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metadata_schema"] = ""
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="plugin manifest field 'metadata_schema' must be a non-empty relative file path"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_string_declared_contract_path(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["metadata_schema"] = 123
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="plugin manifest field 'metadata_schema' must be a string relative file path",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_golden_rules_fields_missing_from_metadata_schema(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "golden_rules.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.golden_rules.v1",
                "expected_metadata": ["business_type", "undeclared_field"],
                "template_selector_fields": ["business_type"],
                "tag_fields": ["business_type"],
                "query_templates": {"demo": ["{business_type}业务怎么处理？"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="golden_rules.expected_metadata references undeclared metadata fields"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_golden_expected_metadata_fields_not_marked_evaluable(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    metadata_schema_path = plugin_dir / "metadata_schema.json"
    metadata_schema = json.loads(metadata_schema_path.read_text(encoding="utf-8"))
    for field in metadata_schema["fields"]:
        if field["name"] == "business_type":
            field["evaluable"] = False
    metadata_schema_path.write_text(json.dumps(metadata_schema, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PipelinePluginRegistryError,
        match="golden_rules.expected_metadata references non-evaluable metadata fields: business_type",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_empty_golden_expected_metadata(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "golden_rules.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.golden_rules.v1",
                "expected_metadata": [],
                "template_selector_fields": ["business_type"],
                "query_templates": {"demo": ["{business_type}业务怎么处理？"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="golden_rules.expected_metadata must declare at least one field"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


@pytest.mark.parametrize("rule_key", ["expected_metadata", "template_selector_fields", "tag_fields"])
def test_plugin_descriptor_rejects_non_list_golden_rule_field_lists(tmp_path: Path, rule_key: str):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["business_type", "chunk_kind"],
        "template_selector_fields": ["business_type"],
        "tag_fields": ["business_type", "chunk_kind"],
        "query_templates": {"demo": ["{business_type}业务怎么处理？"]},
    }
    golden_rules[rule_key] = "business_type"
    (plugin_dir / "golden_rules.json").write_text(json.dumps(golden_rules, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match=f"golden_rules.{rule_key} must be a list"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_empty_declared_metadata_schema(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text("{}", encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="metadata_schema.schema must be mimirq.metadata_schema.v1"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


@pytest.mark.parametrize(
    ("contract_file", "unknown_key", "expected_message"),
    [
        ("metadata_schema.json", "business_defaults", "metadata_schema contains unknown top-level fields: business_defaults"),
        ("retrieval_text_schema.json", "business_boosts", "retrieval_text_schema contains unknown top-level fields: business_boosts"),
        ("golden_rules.json", "district_defaults", "golden_rules contains unknown top-level fields: district_defaults"),
    ],
)
def test_plugin_descriptor_rejects_unknown_contract_top_level_fields(
    tmp_path: Path,
    contract_file: str,
    unknown_key: str,
    expected_message: str,
):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    contract_path = plugin_dir / contract_file
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract[unknown_key] = {"mode": "business-specific"}
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match=expected_message):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_metadata_field_unsupported_stage(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {
                        "name": "business_type",
                        "type": "string",
                        "required": True,
                        "stages": ["business"],
                    },
                    {"name": "chunk_kind", "type": "string", "required": True, "stages": ["chunk"]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="metadata field 'business_type' has unsupported stages: business"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_ambiguous_kg_metadata_field_path(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
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
                    },
                    {
                        "name": "chunk_kind",
                        "type": "string",
                        "required": True,
                        "stages": ["chunk"],
                    },
                    {
                        "name": "event_type",
                        "type": "string",
                        "required": True,
                        "stages": ["kg"],
                    },
                ],
                "record_identity": ["business_type"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata field 'event_type' used by kg must start with metadata\\., references\\., or extra_data\\.",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_metadata_field_non_list_stages(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {"name": "business_type", "type": "string", "required": True, "stages": "chunk"},
                    {"name": "chunk_kind", "type": "string", "required": True, "stages": ["chunk"]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="metadata field 'business_type' stages must be a list"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_unknown_metadata_field_keys(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {
                        "name": "business_type",
                        "type": "string",
                        "required": True,
                        "business_boost": 2,
                    },
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata field 'business_type' contains unknown fields: business_boost",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_string_metadata_field_name(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "record_identity": ["True"],
                "fields": [
                    {"name": True, "type": "string", "required": True},
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
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
                    "chunk": {"fields": [{"metadata": "True", "label": "业务类型"}, {"content": True}]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "golden_rules.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.golden_rules.v1",
                "expected_metadata": ["True"],
                "template_selector_fields": ["True"],
                "tag_fields": ["True"],
                "query_templates": {"demo": ["{True}业务怎么处理？"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata field at index 0 name must be a string",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_reserved_internal_metadata_field_name(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {"name": "_indexed_metadata", "type": "object", "required": False},
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata field '_indexed_metadata' uses reserved platform metadata namespace",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_platform_owned_metadata_field_name(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {"name": "source", "type": "string", "required": False},
                    {"name": "business_type", "type": "string", "required": True},
                    {"name": "chunk_kind", "type": "string", "required": True, "stages": ["chunk"]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata field 'source' uses platform-owned metadata field name",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_reserved_internal_kg_metadata_path(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {"name": "business_type", "type": "string", "required": True, "stages": ["governance", "chunk"]},
                    {"name": "chunk_kind", "type": "string", "required": True, "stages": ["chunk"]},
                    {"name": "metadata._record_identity", "type": "object", "required": False, "stages": ["kg"]},
                ],
                "record_identity": ["business_type"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata field 'metadata._record_identity' uses reserved platform metadata namespace",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_platform_owned_kg_metadata_path(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {"name": "business_type", "type": "string", "required": True, "stages": ["governance", "chunk"]},
                    {"name": "chunk_kind", "type": "string", "required": True, "stages": ["chunk"]},
                    {"name": "metadata.document_id", "type": "string", "required": False, "stages": ["kg"]},
                ],
                "record_identity": ["business_type"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata field 'metadata.document_id' uses platform-owned metadata field name",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_object_metadata_field_items(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    "business_type",
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="metadata field at index 0 must be an object"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


@pytest.mark.parametrize("flag_name", ["required", "filterable", "display", "evaluable"])
def test_plugin_descriptor_rejects_non_boolean_metadata_field_flags(tmp_path: Path, flag_name: str):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    field = {
        "name": "business_type",
        "type": "string",
        "required": True,
        "filterable": True,
        "display": True,
        "evaluable": True,
    }
    field[flag_name] = "false"
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    field,
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match=f"metadata field 'business_type' {flag_name} must be a boolean",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_integer_metadata_field_max_length(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {
                        "name": "business_type",
                        "type": "string",
                        "required": True,
                        "max_length": "80",
                    },
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata field 'business_type' max_length must be an integer",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_list_metadata_field_enum(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "fields": [
                    {
                        "name": "business_type",
                        "type": "string",
                        "required": True,
                        "enum": "demo",
                    },
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata field 'business_type' enum must be a list",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_string_record_identity_items(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "record_identity": [True],
                "fields": [
                    {"name": "True", "type": "string", "required": True},
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {"chunk": {"fields": [{"metadata": "True"}, {"content": True}]}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "golden_rules.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.golden_rules.v1",
                "expected_metadata": ["True"],
                "template_selector_fields": ["True"],
                "tag_fields": ["True"],
                "query_templates": {"demo": ["{True}业务怎么处理？"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match=r"metadata_schema\.record_identity\[0\] must be a string"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


@pytest.mark.parametrize("rule_key", ["expected_metadata", "template_selector_fields", "tag_fields"])
def test_plugin_descriptor_rejects_non_string_golden_rule_field_items(tmp_path: Path, rule_key: str):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
                {
                    "schema": "mimirq.metadata_schema.v1",
                    "record_identity": ["True"],
                    "fields": [
                        {"name": "True", "type": "string", "required": True, "evaluable": True},
                        {"name": "chunk_kind", "type": "string", "required": True},
                    ],
                },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {"chunk": {"fields": [{"metadata": "True"}, {"content": True}]}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["True"],
        "template_selector_fields": ["True"],
        "tag_fields": ["True"],
        "query_templates": {"demo": ["{True}业务怎么处理？"]},
    }
    golden_rules[rule_key] = [True]
    (plugin_dir / "golden_rules.json").write_text(json.dumps(golden_rules, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match=rf"golden_rules\.{rule_key}\[0\] must be a string"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_object_golden_query_templates(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["business_type", "chunk_kind"],
        "template_selector_fields": ["business_type"],
        "tag_fields": ["business_type", "chunk_kind"],
        "query_templates": ["{business_type}业务怎么处理？"],
    }
    (plugin_dir / "golden_rules.json").write_text(json.dumps(golden_rules, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="golden_rules.query_templates must be an object"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_list_golden_query_template_bucket(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["business_type", "chunk_kind"],
        "template_selector_fields": ["business_type"],
        "tag_fields": ["business_type", "chunk_kind"],
        "query_templates": {"demo": "{business_type}业务怎么处理？"},
    }
    (plugin_dir / "golden_rules.json").write_text(json.dumps(golden_rules, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="golden_rules.query_templates.demo must be a list"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_string_golden_query_template_items(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    golden_rules = {
        "schema": "mimirq.golden_rules.v1",
        "expected_metadata": ["business_type", "chunk_kind"],
        "template_selector_fields": ["business_type"],
        "tag_fields": ["business_type", "chunk_kind"],
        "query_templates": {"demo": [True]},
    }
    (plugin_dir / "golden_rules.json").write_text(json.dumps(golden_rules, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match=r"golden_rules\.query_templates\.demo\[0\] must be a string"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_fields_missing_from_metadata_schema(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {
                    "chunk": {
                        "fields": [
                            {"metadata": "business_type", "label": "业务类型"},
                            {"metadata": "undeclared_field", "label": "隐式字段"},
                            {"content": True, "label": "内容"},
                        ]
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="retrieval_text_schema.stages.chunk.fields references undeclared metadata fields",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_unsupported_stage(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {
                    "embedding": {"fields": [{"metadata": "business_type", "label": "业务类型"}]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="retrieval_text_schema.stages contains unsupported stages: embedding",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_kg_stage(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {
                    "kg": {"fields": [{"metadata": "business_type", "label": "业务类型"}]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="retrieval_text_schema.stages contains unsupported stages: kg",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_non_object_stages(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": ["chunk"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="retrieval_text_schema.stages must be an object"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_non_object_stage_spec(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {"chunk": "fields"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="retrieval_text_schema.stages.chunk must be an object",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_stage_non_list_fields(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {
                    "chunk": {"fields": {"metadata": "business_type", "label": "业务类型"}},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="retrieval_text_schema.stages.chunk.fields must be a list"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_unknown_stage_keys(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {
                    "chunk": {
                        "fields": [{"metadata": "business_type", "label": "业务类型"}, {"content": True}],
                        "business_boosts": {"business_type": 2},
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="retrieval_text_schema.stages.chunk contains unknown fields: business_boosts",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_non_object_field_items(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {
                    "chunk": {"fields": ["business_type", {"content": True, "label": "内容"}]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match=r"retrieval_text_schema\.stages\.chunk\.fields\[0\] must be an object",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_unknown_field_keys(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {
                    "chunk": {
                        "fields": [
                            {"metadata": "business_type", "label": "业务类型", "business_boost": 2},
                            {"content": True, "label": "内容"},
                        ]
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match=r"retrieval_text_schema\.stages\.chunk\.fields\[0\] contains unknown fields: business_boost",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_retrieval_text_noop_field_items(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {"chunk": {"fields": [{"label": "业务类型"}, {"content": True, "label": "内容"}]}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match=r"retrieval_text_schema\.stages\.chunk\.fields\[0\] must set metadata or content=true",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_boolean_retrieval_text_content_flag(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {"chunk": {"fields": [{"content": "true", "label": "内容"}]}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match=r"retrieval_text_schema\.stages\.chunk\.fields\[0\]\.content must be a boolean",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_string_retrieval_text_metadata_field(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "record_identity": ["True"],
                "fields": [
                    {"name": "True", "type": "string", "required": True},
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v1",
                "stages": {"chunk": {"fields": [{"metadata": True, "label": "业务类型"}, {"content": True}]}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (plugin_dir / "golden_rules.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.golden_rules.v1",
                "expected_metadata": ["True"],
                "template_selector_fields": ["True"],
                "tag_fields": ["True"],
                "query_templates": {"demo": ["{True}业务怎么处理？"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match=r"retrieval_text_schema\.stages\.chunk\.fields\[0\]\.metadata must be a string",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_invalid_retrieval_text_schema_version(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "retrieval_text_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.retrieval_text_schema.v0",
                "stages": {"chunk": {"fields": [{"metadata": "business_type", "label": "业务类型"}]}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="retrieval_text_schema.schema must be mimirq.retrieval_text_schema.v1"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_invalid_golden_rules_schema_version(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "golden_rules.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.golden_rules.v0",
                "expected_metadata": ["business_type"],
                "query_templates": {"demo": ["{business_type}业务怎么处理？"]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="golden_rules.schema must be mimirq.golden_rules.v1"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_record_identity_fields_missing_from_metadata_schema(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "record_identity": ["business_type", "undeclared_record_key"],
                "fields": [
                    {"name": "business_type", "type": "string", "required": True},
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        PipelinePluginRegistryError,
        match="metadata_schema.record_identity references undeclared metadata fields",
    ):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_non_list_record_identity(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    (plugin_dir / "metadata_schema.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.metadata_schema.v1",
                "record_identity": "business_type",
                "fields": [
                    {"name": "business_type", "type": "string", "required": True},
                    {"name": "chunk_kind", "type": "string", "required": True},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="metadata_schema.record_identity must be a list"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_import_entry_outside_plugin_directory(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"]["governance"] = "json:dumps"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="plugin entry module must resolve inside plugin directory"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_platform_named_local_entry_module(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    platform_named_dir = plugin_dir / "app" / "services"
    platform_named_dir.mkdir(parents=True)
    (plugin_dir / "app" / "__init__.py").write_text("", encoding="utf-8")
    (platform_named_dir / "__init__.py").write_text("", encoding="utf-8")
    (platform_named_dir / "business_rules.py").write_text(
        "def govern_documents(documents, params=None, context=None):\n    return documents\n",
        encoding="utf-8",
    )
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"]["governance"] = "app.services.business_rules:govern_documents"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="plugin entry module must not use platform package names"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_platform_named_local_entry_file(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    platform_named_dir = plugin_dir / "app" / "services"
    platform_named_dir.mkdir(parents=True)
    (platform_named_dir / "business_rules.py").write_text(
        "def govern_documents(documents, params=None, context=None):\n    return documents\n",
        encoding="utf-8",
    )
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"]["governance"] = "app/services/business_rules.py:govern_documents"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="plugin entry file must not use platform package names"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_plugin_source_importing_platform_app_modules(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "from app.rag.pipeline_plugins.runtime import apply_chunk_python_plugin",
                "",
                "def marker():",
                "    return apply_chunk_python_plugin",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_dynamic_platform_app_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "import importlib",
                "",
                "def marker():",
                "    return importlib.import_module('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_import_module_alias_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "from importlib import import_module as load_module",
                "",
                "def marker():",
                "    return load_module('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_importlib_attribute_assignment_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "import importlib as imports",
                "load_module = imports.import_module",
                "",
                "def marker():",
                "    return load_module('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_importlib_module_assignment_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "import importlib",
                "imports = importlib",
                "",
                "def marker():",
                "    return imports.import_module('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_dynamic_platform_imports_with_keyword_name(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "import importlib",
                "",
                "def marker():",
                "    return importlib.import_module(name='app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_getattr_importlib_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "import importlib",
                "",
                "def marker():",
                "    return getattr(importlib, 'import_module')('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_getattr_importlib_assignment_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "import importlib",
                "load_module = getattr(importlib, 'import_module')",
                "",
                "def marker():",
                "    return load_module('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_builtins_import_attribute_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "import builtins",
                "",
                "def marker():",
                "    return builtins.__import__('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_builtins_import_from_alias_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "from builtins import __import__ as load_module",
                "",
                "def marker():",
                "    return load_module('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_getattr_builtins_import_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "import builtins",
                "",
                "def marker():",
                "    return getattr(builtins, '__import__')('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_dunder_builtins_import_attribute_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "def marker():",
                "    return __builtins__.__import__('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_dunder_builtins_import_subscript_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "def marker():",
                "    return __builtins__['__import__']('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_dunder_builtins_import_subscript_assignment_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "load_module = __builtins__['__import__']",
                "",
                "def marker():",
                "    return load_module('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_import_builtin_assignment_platform_imports(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "helper.py").write_text(
        "\n".join(
            [
                "load_module = __import__",
                "",
                "def marker():",
                "    return load_module('app.rag.pipeline_plugins.runtime')",
                "",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source helper.py must not dynamically import platform module app"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_platform_named_helper_source_file(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    helper_dir = plugin_dir / "app" / "business"
    helper_dir.mkdir(parents=True)
    (helper_dir / "rules.py").write_text(
        "VALUE = 'business'\n",
        encoding="utf-8",
    )

    with pytest.raises(PipelinePluginRegistryError, match="plugin source file must not use platform package names"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_descriptor_rejects_unknown_entry_stage(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"]["business_enrichment"] = "plugin.py:govern_documents"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="plugin manifest entry contains unsupported stages: business_enrichment"):
        describe_plugin_dir(plugin_dir, require_test_report=False)


def test_plugin_package_hash_includes_python_helper_files(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    before_hash = describe_plugin_dir(plugin_dir, require_test_report=False).package_hash

    helper_path = plugin_dir / "rules.py"
    helper_path.write_text("VALUE = 'v1'\n", encoding="utf-8")
    helper_hash = describe_plugin_dir(plugin_dir, require_test_report=False).package_hash

    assert helper_hash != before_hash

    helper_path.write_text("VALUE = 'v2'\n", encoding="utf-8")
    assert describe_plugin_dir(plugin_dir, require_test_report=False).package_hash != helper_hash


def test_plugin_package_hash_includes_resource_files_but_not_test_report(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PLUGIN_TEST_REPORT_FILENAME, describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    before_hash = describe_plugin_dir(plugin_dir, require_test_report=False).package_hash

    resource_path = plugin_dir / "synonyms.json"
    resource_path.write_text('{"record": ["account renewal"]}\n', encoding="utf-8")
    resource_hash = describe_plugin_dir(plugin_dir, require_test_report=False).package_hash

    assert resource_hash != before_hash

    resource_path.write_text('{"record": ["account update", "account renewal"]}\n', encoding="utf-8")
    changed_resource_hash = describe_plugin_dir(plugin_dir, require_test_report=False).package_hash
    assert changed_resource_hash != resource_hash

    (plugin_dir / PLUGIN_TEST_REPORT_FILENAME).write_text('{"passed": true}\n', encoding="utf-8")
    assert describe_plugin_dir(plugin_dir, require_test_report=False).package_hash == changed_resource_hash


def test_plugin_package_hash_ignores_docs_but_includes_samples(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    before_hash = describe_plugin_dir(plugin_dir, require_test_report=False).package_hash

    (plugin_dir / "README.md").write_text("# demo docs\n", encoding="utf-8")
    assert describe_plugin_dir(plugin_dir, require_test_report=False).package_hash == before_hash

    sample_path = plugin_dir / "sample.json"
    sample_path.write_text('[{"page_content":"hello"}]\n', encoding="utf-8")
    sample_hash = describe_plugin_dir(plugin_dir, require_test_report=False).package_hash
    assert sample_hash != before_hash

    sample_path.write_text('[{"page_content":"changed"}]\n', encoding="utf-8")
    assert describe_plugin_dir(plugin_dir, require_test_report=False).package_hash != sample_hash


def test_file_entry_plugin_reload_uses_updated_helper_module(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from langchain_core.documents import Document",
                "import rules",
                "",
                "def govern_documents(documents, params=None, context=None):",
                "    return [Document(page_content=rules.VALUE, metadata={})]",
                "",
                "def chunk_documents(documents, params=None, context=None):",
                "    return documents",
                "",
            ]
        ),
        encoding="utf-8",
    )
    helper_path = plugin_dir / "rules.py"
    helper_path.write_text("VALUE = 'v1'\n", encoding="utf-8")

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    first = load_descriptor_stage_callable(descriptor, "governance")([], {}, {})

    helper_path.write_text("VALUE = 'v2'\n", encoding="utf-8")
    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    second = load_descriptor_stage_callable(descriptor, "governance")([], {}, {})

    assert first[0].page_content == "v1"
    assert second[0].page_content == "v2"


def test_module_entry_plugin_reload_uses_updated_helper_module(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"]["governance"] = "plugin:govern_documents"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from langchain_core.documents import Document",
                "import rules",
                "",
                "def govern_documents(documents, params=None, context=None):",
                "    return [Document(page_content=rules.VALUE, metadata={})]",
                "",
                "def chunk_documents(documents, params=None, context=None):",
                "    return documents",
                "",
            ]
        ),
        encoding="utf-8",
    )
    helper_path = plugin_dir / "rules.py"
    helper_path.write_text("VALUE = 'v1'\n", encoding="utf-8")

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    first = load_descriptor_stage_callable(descriptor, "governance")([], {}, {})

    helper_path.write_text("VALUE = 'v2'\n", encoding="utf-8")
    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    second = load_descriptor_stage_callable(descriptor, "governance")([], {}, {})

    assert first[0].page_content == "v1"
    assert second[0].page_content == "v2"


def test_file_entry_plugin_local_helper_shadow_does_not_pollute_global_modules(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    stdlib_json = sys.modules["json"]
    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from langchain_core.documents import Document",
                "import json",
                "",
                "def govern_documents(documents, params=None, context=None):",
                "    return [Document(page_content=json.VALUE, metadata={})]",
                "",
                "def chunk_documents(documents, params=None, context=None):",
                "    return documents",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "json.py").write_text("VALUE = 'plugin-local'\n", encoding="utf-8")

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    result = load_descriptor_stage_callable(descriptor, "governance")([], {}, {})

    assert result[0].page_content == "plugin-local"
    assert sys.modules["json"] is stdlib_json


def test_file_entry_plugin_function_can_lazy_import_local_helper(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from langchain_core.documents import Document",
                "",
                "def govern_documents(documents, params=None, context=None):",
                "    import rules",
                "    return [Document(page_content=rules.VALUE, metadata={})]",
                "",
                "def chunk_documents(documents, params=None, context=None):",
                "    return documents",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "rules.py").write_text("VALUE = 'lazy-local'\n", encoding="utf-8")

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    result = load_descriptor_stage_callable(descriptor, "governance")([], {}, {})

    assert result[0].page_content == "lazy-local"


def test_file_entry_plugin_lazy_import_does_not_leave_bytecode_cache(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from langchain_core.documents import Document",
                "",
                "def govern_documents(documents, params=None, context=None):",
                "    import rules",
                "    return [Document(page_content=rules.VALUE, metadata={})]",
                "",
                "def chunk_documents(documents, params=None, context=None):",
                "    return documents",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "rules.py").write_text("VALUE = 'lazy-local'\n", encoding="utf-8")

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    result = load_descriptor_stage_callable(descriptor, "governance")([], {}, {})

    assert result[0].page_content == "lazy-local"
    assert not list(plugin_dir.rglob("__pycache__"))
    assert not list(plugin_dir.rglob("*.pyc"))


def test_file_entry_plugin_load_does_not_leave_bytecode_cache(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    func = load_descriptor_stage_callable(descriptor, "governance")

    assert callable(func)
    assert not list(plugin_dir.rglob("__pycache__"))
    assert not list(plugin_dir.rglob("*.pyc"))


def test_module_entry_plugin_function_can_lazy_import_local_helper(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entry"]["governance"] = "plugin:govern_documents"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from langchain_core.documents import Document",
                "",
                "def govern_documents(documents, params=None, context=None):",
                "    import rules",
                "    return [Document(page_content=rules.VALUE, metadata={})]",
                "",
                "def chunk_documents(documents, params=None, context=None):",
                "    return documents",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "rules.py").write_text("VALUE = 'lazy-module-local'\n", encoding="utf-8")

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    result = load_descriptor_stage_callable(descriptor, "governance")([], {}, {})

    assert result[0].page_content == "lazy-module-local"


def test_file_entry_generator_plugin_can_lazy_import_local_helper(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from langchain_core.documents import Document",
                "",
                "def govern_documents(documents, params=None, context=None):",
                "    import rules",
                "    yield Document(page_content=rules.VALUE, metadata={})",
                "",
                "def chunk_documents(documents, params=None, context=None):",
                "    return documents",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "rules.py").write_text("VALUE = 'lazy-generator-local'\n", encoding="utf-8")

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    result = list(load_descriptor_stage_callable(descriptor, "governance")([], {}, {}))

    assert result[0].page_content == "lazy-generator-local"


def test_generator_plugin_cleans_local_import_context_between_yields(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    (plugin_dir / "plugin.py").write_text(
        "\n".join(
            [
                "from langchain_core.documents import Document",
                "",
                "def govern_documents(documents, params=None, context=None):",
                "    import rules",
                "    yield Document(page_content=rules.VALUE, metadata={})",
                "    import more_rules",
                "    yield Document(page_content=more_rules.VALUE, metadata={})",
                "",
                "def chunk_documents(documents, params=None, context=None):",
                "    return documents",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (plugin_dir / "rules.py").write_text("VALUE = 'first'\n", encoding="utf-8")
    (plugin_dir / "more_rules.py").write_text("VALUE = 'second'\n", encoding="utf-8")

    descriptor = describe_plugin_dir(plugin_dir, require_test_report=False)
    iterator = load_descriptor_stage_callable(descriptor, "governance")([], {}, {})

    assert next(iterator).page_content == "first"
    assert str(plugin_dir.resolve()) not in sys.path
    assert "rules" not in sys.modules
    assert "more_rules" not in sys.modules
    assert next(iterator).page_content == "second"
    assert str(plugin_dir.resolve()) not in sys.path
    assert "more_rules" not in sys.modules


def test_concurrent_file_entry_loads_do_not_cross_import_plugin_helpers(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import describe_plugin_dir, load_descriptor_stage_callable

    gate_module_name = "_mimirq_plugin_concurrency_gate"
    gate = types.ModuleType(gate_module_name)

    def delay(label: str) -> None:
        if label == "a":
            time.sleep(0.10)

    def hold(label: str) -> None:
        if label == "b":
            time.sleep(0.20)

    gate.delay = delay  # type: ignore[attr-defined]
    gate.hold = hold  # type: ignore[attr-defined]
    sys.modules[gate_module_name] = gate

    try:
        roots = tmp_path / "plugins"
        plugin_a = roots / "demo-a"
        plugin_b = roots / "demo-b"
        _write_demo_plugin(plugin_a)
        _write_demo_plugin(plugin_b)
        for label, plugin_dir in (("a", plugin_a), ("b", plugin_b)):
            manifest_path = plugin_dir / "mimirq-plugin.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["id"] = f"demo-{label}"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (plugin_dir / "rules.py").write_text(f"VALUE = '{label}'\n", encoding="utf-8")
            (plugin_dir / "plugin.py").write_text(
                "\n".join(
                    [
                        "from langchain_core.documents import Document",
                        f"import {gate_module_name} as gate",
                        f"gate.delay('{label}')",
                        "import rules",
                        f"gate.hold('{label}')",
                        "",
                        "def govern_documents(documents, params=None, context=None):",
                        "    return [Document(page_content=rules.VALUE, metadata={})]",
                        "",
                        "def chunk_documents(documents, params=None, context=None):",
                        "    return documents",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

        descriptors = [
            describe_plugin_dir(plugin_a, require_test_report=False),
            describe_plugin_dir(plugin_b, require_test_report=False),
        ]

        def load_value(index: int) -> str:
            func = load_descriptor_stage_callable(descriptors[index], "governance")
            return func([], {}, {})[0].page_content

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            values = list(executor.map(load_value, [0, 1]))

        assert values == ["a", "b"]
    finally:
        sys.modules.pop(gate_module_name, None)


def test_resolve_registered_plugin_descriptor_rejects_missing_stage(tmp_path: Path):
    from app.rag.pipeline_plugins.registry import PipelinePluginRegistryError, resolve_registered_plugin_descriptor

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir)
    manifest_path = plugin_dir / "mimirq-plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["entry"]["chunk"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PipelinePluginRegistryError, match="has no chunk entry"):
        resolve_registered_plugin_descriptor(
            "plugin:demo-service@1.0.0:chunk",
            directories=[tmp_path / "plugins"],
            require_test_report=False,
        )


def test_metadata_schema_views_are_generic_and_schema_driven():
    from app.rag.core.filters import match_metadata_filter
    from app.rag.pipeline_plugins.contracts import (
        DISPLAY_METADATA_KEY,
        EVALUABLE_METADATA_KEY,
        INDEXED_METADATA_KEY,
        RECORD_IDENTITY_METADATA_KEY,
        apply_metadata_schema_views,
    )

    schema = {
        "schema": "mimirq.metadata_schema.v1",
        "record_identity": ["business_type", "region"],
        "fields": [
            {"name": "business_type", "type": "string", "stages": ["chunk"], "filterable": True, "display": True},
            {"name": "region", "type": "string", "stages": ["chunk"], "filterable": True, "evaluable": True},
            {"name": "internal_note", "type": "string", "stages": ["chunk"]},
        ],
    }
    docs = apply_metadata_schema_views(
        [
            Document(
                page_content="body",
                metadata={"business_type": "contract", "region": "east", "internal_note": "private"},
            )
        ],
        metadata_schema=schema,
        stage="chunk",
    )
    meta = docs[0].metadata

    assert meta[INDEXED_METADATA_KEY] == {"business_type": "contract", "region": "east"}
    assert meta[DISPLAY_METADATA_KEY] == {"business_type": "contract"}
    assert meta[EVALUABLE_METADATA_KEY] == {"region": "east"}
    assert meta[RECORD_IDENTITY_METADATA_KEY]["fields"] == {"business_type": "contract", "region": "east"}
    assert meta[RECORD_IDENTITY_METADATA_KEY]["key"] == "business_type=contract|region=east"
    assert "internal_note" not in meta[INDEXED_METADATA_KEY]
    assert match_metadata_filter(meta, {"_indexed_metadata.business_type": "contract"}) is True


def test_reserved_platform_metadata_view_keys_are_exported_as_contract():
    from app.rag.pipeline_plugins.contracts import (
        DISPLAY_METADATA_KEY,
        EVALUABLE_METADATA_KEY,
        INDEXED_METADATA_KEY,
        RECORD_IDENTITY_METADATA_KEY,
        RESERVED_PLATFORM_METADATA_VIEW_KEYS,
        RETRIEVAL_DISPLAY_CONTENT_METADATA_KEY,
        RETRIEVAL_TEXT_METADATA_KEY,
    )

    assert RESERVED_PLATFORM_METADATA_VIEW_KEYS == (
        INDEXED_METADATA_KEY,
        DISPLAY_METADATA_KEY,
        EVALUABLE_METADATA_KEY,
        RECORD_IDENTITY_METADATA_KEY,
        RETRIEVAL_TEXT_METADATA_KEY,
        RETRIEVAL_DISPLAY_CONTENT_METADATA_KEY,
    )


def test_metadata_schema_view_keys_are_exported_as_contract():
    from app.rag.pipeline_plugins.contracts import (
        DISPLAY_METADATA_KEY,
        EVALUABLE_METADATA_KEY,
        INDEXED_METADATA_KEY,
        METADATA_SCHEMA_VIEW_KEYS,
        RECORD_IDENTITY_METADATA_KEY,
    )

    assert METADATA_SCHEMA_VIEW_KEYS == (
        INDEXED_METADATA_KEY,
        DISPLAY_METADATA_KEY,
        EVALUABLE_METADATA_KEY,
        RECORD_IDENTITY_METADATA_KEY,
    )


def test_registered_plugin_runtime_validates_required_metadata_and_builds_retrieval_text(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test
    from app.rag.pipeline_plugins.runtime import apply_chunk_python_plugin, apply_governance_python_plugin

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")
    run_pipeline_plugin_test(plugin_dir, input_path=sample_path, stages=["governance", "chunk"])
    plugin_ref = "plugin:demo-service@1.0.0:governance"
    chunk_ref = "plugin:demo-service@1.0.0:chunk"

    governed = apply_governance_python_plugin(
        [Document(page_content="live", metadata={})],
        plugin_ref=plugin_ref,
        context={"plugin_directories": [tmp_path / "plugins"]},
    )
    chunks = apply_chunk_python_plugin(
        governed,
        plugin_ref=chunk_ref,
        context={"plugin_directories": [tmp_path / "plugins"]},
    )

    assert chunks[0].page_content == "live::v1"
    assert chunks[0].metadata["_retrieval_display_content"] == "live::v1"
    assert chunks[0].metadata["_retrieval_text"] == "业务类型：demo\n切块类型：demo\n内容：live::v1"
    assert chunks[0].metadata["_indexed_metadata"] == {"business_type": "demo", "chunk_kind": "demo"}
    assert chunks[0].metadata["_display_metadata"] == {"business_type": "demo", "chunk_kind": "demo"}
    assert chunks[0].metadata["_evaluable_metadata"] == {"business_type": "demo", "chunk_kind": "demo"}
    assert chunks[0].metadata["_record_identity"]["fields"] == {"business_type": "demo"}


def test_registered_plugin_runtime_rejects_missing_required_metadata(tmp_path: Path):
    from app.rag.pipeline_plugins.local_runner import run_pipeline_plugin_test
    from app.rag.pipeline_plugins.runtime import PythonPipelinePluginError, apply_governance_python_plugin

    plugin_dir = tmp_path / "plugins" / "demo"
    _write_demo_plugin(plugin_dir, include_contracts=True, omit_required_metadata=True)
    sample_path = tmp_path / "sample.json"
    sample_path.write_text(json.dumps([{"page_content": "hello"}]), encoding="utf-8")

    with pytest.raises(PythonPipelinePluginError, match="business_type"):
        apply_governance_python_plugin(
            [Document(page_content="live", metadata={})],
            plugin_ref="plugin:demo-service@1.0.0:governance",
            context={"plugin_directories": [tmp_path / "plugins"]},
        )

    report = run_pipeline_plugin_test(
        plugin_dir,
        input_path=sample_path,
        stages=["governance"],
        write_report=False,
    )
    assert report["passed"] is False
    assert report["stages"]["governance"]["metadata_validation"]["ok"] is False
