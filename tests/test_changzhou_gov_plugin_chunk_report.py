from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "changzhou_gov_plugin_chunk_report.py"
PLUGIN_DIR = REPO_ROOT / "plugins" / "pipelines" / "changzhou-gov-service-knowledge"
SAMPLE_PATH = PLUGIN_DIR / "sample.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("changzhou_gov_plugin_chunk_report", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_chunk_report_covers_all_changzhou_sections() -> None:
    mod = _load_module()

    report = mod.build_chunk_report(
        PLUGIN_DIR,
        input_path=SAMPLE_PATH,
        max_examples_per_section=1,
        preview_chars=120,
    )

    assert report["schema"] == "mimirq.changzhou_gov_service_knowledge.chunk_report.v1"
    assert report["passed"] is True
    assert report["summary"]["input_documents"] == 8
    assert report["summary"]["governed_records"] >= 8
    assert report["summary"]["chunks"] >= report["summary"]["governed_records"]
    assert report["summary"]["kg_events"] >= 1

    sections = {section["knowledge_section"]: section for section in report["sections"]}
    assert {
        "01政务服务事项知识",
        "02高效办成一件事",
        "03常州市常见问题",
        "04专题常见问答",
        "05业务部门常见问题",
        "06各区常见问题",
    }.issubset(sections)

    assert sections["01政务服务事项知识"]["chunk_kinds"]["service_item_full"] >= 1
    assert "one_thing_operation_steps" in sections["02高效办成一件事"]["chunk_kinds"]
    assert sections["03常州市常见问题"]["chunk_kinds"]["qa_pair"] >= 1
    assert sections["04专题常见问答"]["chunk_kinds"]["qa_pair"] >= 1
    assert sections["06各区常见问题"]["chunk_kinds"]["qa_pair"] >= 1
    assert "kg_entity_types" in sections["05业务部门常见问题"]
    assert all(section["examples"] for section in sections.values())


def test_format_markdown_report_is_reviewable_without_full_raw_dump() -> None:
    mod = _load_module()
    report = mod.build_chunk_report(
        PLUGIN_DIR,
        input_path=SAMPLE_PATH,
        max_examples_per_section=1,
        preview_chars=80,
    )

    text = mod.format_markdown_report(report)

    assert "# Changzhou Gov Plugin Chunk Report" in text
    assert "| 01政务服务事项知识 |" in text
    assert "service_item_full" in text
    assert "one_thing_operation_steps" in text
    assert "kg_entity_types" in text
    assert "utm_source" not in text
    assert len(text) < 20_000


def test_main_writes_json_and_markdown_reports(tmp_path: Path) -> None:
    mod = _load_module()
    json_path = tmp_path / "chunk_report.json"
    markdown_path = tmp_path / "chunk_report.md"

    rc = mod.main(
        [
            "--plugin-dir",
            str(PLUGIN_DIR),
            "--input",
            str(SAMPLE_PATH),
            "--json-out",
            str(json_path),
            "--markdown-out",
            str(markdown_path),
            "--max-examples-per-section",
            "1",
            "--preview-chars",
            "80",
        ]
    )

    assert rc == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert "01政务服务事项知识" in markdown_path.read_text(encoding="utf-8")
