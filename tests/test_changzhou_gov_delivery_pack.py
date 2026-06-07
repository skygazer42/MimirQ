from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "changzhou_gov_delivery_pack.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("changzhou_gov_delivery_pack", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _plugin_test_payload() -> dict:
    return {
        "passed": True,
        "stages": {
            "governance": {"passed": True},
            "chunk": {"passed": True},
            "kg": {"passed": True},
        },
        "golden_draft": {"passed": True, "items_total": 20},
    }


def test_build_delivery_pack_combines_plugin_and_readiness_without_raw_answers(tmp_path: Path) -> None:
    mod = _load_module()
    plugin_report = tmp_path / "plugin_report.json"
    plugin_test_report = tmp_path / "plugin_test_report.json"
    plugin_test_evidence = tmp_path / "plugin_test_evidence.json"
    readiness_summary = tmp_path / "readiness_summary.json"
    plugin_md = tmp_path / "plugin_report.md"
    readiness_md = tmp_path / "readiness_evidence.md"
    plugin_md.write_text("# Plugin report\n", encoding="utf-8")
    readiness_md.write_text("# Readiness evidence\n", encoding="utf-8")
    _write_json(
        plugin_report,
        {
            "schema": "mimirq.changzhou_gov_service_knowledge.chunk_report.v1",
            "passed": True,
            "generated_at": "2026-06-07T05:16:58Z",
            "plugin": {"id": "changzhou-gov-service-knowledge", "version": "1.0.0", "package_hash": "abc"},
            "summary": {"input_documents": 8, "governed_records": 8, "chunks": 11, "kg_events": 11, "sections": 6},
            "sections": [
                {
                    "knowledge_section": "01政务服务事项知识",
                    "governed_records": 1,
                    "chunks": 1,
                    "chunk_kinds": {"service_item_full": 1},
                    "metadata_fields": ["district", "service_name"],
                    "kg_entity_types": ["ServiceItem", "District"],
                    "examples": [{"content_preview": "raw sample preview should not be copied"}],
                },
                {
                    "knowledge_section": "02高效办成一件事",
                    "governed_records": 2,
                    "chunks": 5,
                    "chunk_kinds": {"one_thing_operation_steps": 1},
                    "metadata_fields": ["case_title", "section_type"],
                    "kg_entity_types": ["OneThingCase", "OperationStep"],
                },
            ],
        },
    )
    _write_json(
        plugin_test_report,
        _plugin_test_payload()
        | {"golden_draft": {"passed": True, "items_total": 20, "sample_questions": ["真实 Golden 草稿问题不能进入交付包"]}},
    )
    _write_json(
        plugin_test_evidence,
        {
            "schema": "mimirq.changzhou_gov.plugin_test_evidence.v1",
            "passed": True,
            "stage_count": 3,
            "stages": {"chunk": True, "governance": True, "kg": True},
            "failed_stages": [],
            "missing_stages": [],
            "golden_draft": {"passed": True, "items_total": 20},
        },
    )
    _write_json(
        readiness_summary,
        {
            "generated_at": "2026-06-07T04:49:28Z",
            "summary": {"passed": True, "failed_stages": [], "stage_count": 5},
            "external_probe": {
                "status": "passed",
                "boundary": {"verdict": "dify_external_boundary_ok"},
                "summary": {"dify_hit_nonempty": 13, "probe_errors": 0},
            },
            "mimirq_direct": {"status": "passed", "summary": {"cases": 13, "hit_at_1": 1.0}},
            "full_gate": {
                "status": "passed",
                "stages": {
                    "eval": {
                        "summary": {
                            "generated_answer_grounding_rate": 1.0,
                            "generated_answer_policy_clean_rate": 1.0,
                        }
                    },
                    "trace": {"summary": {"route_mismatch_cases": 0, "empty_retrieval_cases": 0}},
                },
            },
            "answers": [{"query": "真实用户问题不能进入交付包", "answer": "真实生成答案不能进入交付包"}],
        },
    )

    pack = mod.build_delivery_pack(
        plugin_report_path=plugin_report,
        plugin_test_report_path=plugin_test_report,
        plugin_test_evidence_path=plugin_test_evidence,
        plugin_markdown_path=plugin_md,
        readiness_summary_path=readiness_summary,
        readiness_evidence_path=readiness_md,
        max_readiness_age_minutes=0,
    )
    text = mod.format_markdown_pack(pack)

    assert pack["schema"] == "mimirq.changzhou_gov.delivery_pack.v1"
    assert pack["passed"] is True
    assert pack["summary"]["plugin_test_passed"] is True
    assert pack["summary"]["plugin_golden_draft_passed"] is True
    assert pack["summary"]["plugin_golden_draft_items"] == 20
    assert "plugin_test_evidence_json" in pack["artifacts"]
    assert "plugin_test_report_json" not in pack["artifacts"]
    assert pack["summary"]["plugin_chunks"] == 11
    assert pack["summary"]["readiness_boundary"] == "dify_external_boundary_ok"
    assert "01政务服务事项知识" in text
    assert "service_item_full" in text
    assert "one_thing_operation_steps" in text
    assert "dify_external_boundary_ok" in text
    assert "| route_mismatch_cases | 0 |" in text
    assert "| empty_retrieval_cases | 0 |" in text
    assert "make changzhou-gov-plugin-test-report" in text
    assert "Golden draft sample questions" in text
    assert "真实用户问题不能进入交付包" not in text
    assert "真实生成答案不能进入交付包" not in text
    assert "真实 Golden 草稿问题不能进入交付包" not in text
    assert "raw sample preview should not be copied" not in text


def test_main_writes_delivery_pack_json_and_markdown(tmp_path: Path) -> None:
    mod = _load_module()
    plugin_report = tmp_path / "plugin_report.json"
    plugin_test_report = tmp_path / "plugin_test_report.json"
    plugin_test_evidence = tmp_path / "plugin_test_evidence.json"
    readiness_summary = tmp_path / "readiness_summary.json"
    json_out = tmp_path / "delivery_pack.json"
    markdown_out = tmp_path / "delivery_pack.md"
    _write_json(
        plugin_report,
        {
            "passed": True,
            "plugin": {"id": "changzhou-gov-service-knowledge", "version": "1.0.0"},
            "summary": {"input_documents": 8, "governed_records": 8, "chunks": 11, "kg_events": 11, "sections": 6},
            "sections": [],
        },
    )
    _write_json(plugin_test_report, _plugin_test_payload())
    _write_json(plugin_test_evidence, {"passed": True})
    _write_json(
        readiness_summary,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "summary": {"passed": True},
            "external_probe": {"boundary": {"verdict": "ok"}},
        },
    )

    rc = mod.main(
        [
            "--plugin-report",
            str(plugin_report),
            "--plugin-test-report",
            str(plugin_test_report),
            "--plugin-test-evidence",
            str(plugin_test_evidence),
            "--readiness-summary",
            str(readiness_summary),
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(markdown_out),
        ]
    )

    assert rc == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["passed"] is True
    assert "# Changzhou Gov Delivery Pack" in markdown_out.read_text(encoding="utf-8")


def test_delivery_pack_fails_stale_readiness_summary(tmp_path: Path) -> None:
    mod = _load_module()
    plugin_report = tmp_path / "plugin_report.json"
    plugin_test_report = tmp_path / "plugin_test_report.json"
    plugin_test_evidence = tmp_path / "plugin_test_evidence.json"
    readiness_summary = tmp_path / "readiness_summary.json"
    _write_json(
        plugin_report,
        {
            "passed": True,
            "summary": {"input_documents": 1, "governed_records": 1, "chunks": 1, "kg_events": 1, "sections": 1},
            "sections": [],
        },
    )
    _write_json(plugin_test_report, _plugin_test_payload())
    _write_json(plugin_test_evidence, {"passed": True})
    _write_json(
        readiness_summary,
        {
            "generated_at": "2026-06-07T04:49:28Z",
            "summary": {"passed": True},
            "external_probe": {"boundary": {"verdict": "ok"}},
        },
    )

    pack = mod.build_delivery_pack(
        plugin_report_path=plugin_report,
        plugin_test_report_path=plugin_test_report,
        plugin_test_evidence_path=plugin_test_evidence,
        readiness_summary_path=readiness_summary,
        now=datetime(2026, 6, 7, 5, 30, tzinfo=UTC),
        max_readiness_age_minutes=30,
    )

    assert pack["passed"] is False
    assert pack["summary"]["readiness_fresh"] is False
    assert pack["readiness"]["freshness"]["status"] == "STALE"


def test_delivery_pack_fails_incomplete_plugin_test_report(tmp_path: Path) -> None:
    mod = _load_module()
    plugin_report = tmp_path / "plugin_report.json"
    plugin_test_report = tmp_path / "plugin_test_report.json"
    plugin_test_evidence = tmp_path / "plugin_test_evidence.json"
    readiness_summary = tmp_path / "readiness_summary.json"
    _write_json(
        plugin_report,
        {
            "passed": True,
            "summary": {"input_documents": 1, "governed_records": 1, "chunks": 1, "kg_events": 1, "sections": 1},
            "sections": [],
        },
    )
    incomplete = _plugin_test_payload()
    incomplete["stages"].pop("kg")
    _write_json(plugin_test_report, incomplete)
    _write_json(plugin_test_evidence, {"passed": False})
    _write_json(
        readiness_summary,
        {
            "generated_at": datetime.now(UTC).isoformat(),
            "summary": {"passed": True},
            "external_probe": {"boundary": {"verdict": "ok"}},
        },
    )

    pack = mod.build_delivery_pack(
        plugin_report_path=plugin_report,
        plugin_test_report_path=plugin_test_report,
        plugin_test_evidence_path=plugin_test_evidence,
        readiness_summary_path=readiness_summary,
    )

    assert pack["passed"] is False
    assert pack["summary"]["plugin_test_passed"] is False
    assert pack["plugin"]["test"]["missing_stages"] == ["kg"]
