from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "changzhou_gov_plugin_chunk_evidence.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("changzhou_gov_plugin_chunk_evidence", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_report() -> dict:
    return {
        "passed": True,
        "plugin": {"id": "changzhou-gov-service-knowledge", "version": "1.0.0", "package_hash": "abc"},
        "summary": {"input_documents": 8, "governed_records": 8, "chunks": 11, "kg_events": 11, "sections": 6},
        "sections": [
            {
                "knowledge_section": "01政务服务事项知识",
                "governed_records": 1,
                "chunks": 1,
                "kg_events": 1,
                "gov_knowledge_types": {"service_item": 1},
                "chunk_kinds": {"service_item_full": 1},
                "metadata_fields": ["district", "service_name"],
                "kg_entity_types": ["District", "ServiceItem"],
                "examples": [
                    {
                        "title": "社会保障卡补卡",
                        "content_preview": "区县：经开区 事项名称：社会保障卡补卡 办理材料：居民身份证件",
                    }
                ],
            }
        ],
    }


def test_plugin_chunk_evidence_sanitizes_examples_and_content_previews(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps(_raw_report(), ensure_ascii=False), encoding="utf-8")

    evidence = mod.build_evidence(raw_path)
    text = json.dumps(evidence, ensure_ascii=False)
    markdown = mod.format_markdown(evidence)

    assert evidence["schema"] == "mimirq.changzhou_gov.plugin_chunk_evidence.v1"
    assert evidence["passed"] is True
    assert evidence["summary"]["chunks"] == 11
    assert evidence["sections"][0]["chunk_kinds"] == {"service_item_full": 1}
    assert "examples" not in evidence["sections"][0]
    assert "content_preview" not in text
    assert "社会保障卡补卡" not in text
    assert "社会保障卡补卡" not in markdown


def test_plugin_chunk_evidence_main_writes_json_and_markdown(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = tmp_path / "raw.json"
    json_out = tmp_path / "evidence.json"
    markdown_out = tmp_path / "evidence.md"
    raw_path.write_text(json.dumps(_raw_report(), ensure_ascii=False), encoding="utf-8")

    rc = mod.main(
        [
            "--input",
            str(raw_path),
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(markdown_out),
        ]
    )

    assert rc == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["passed"] is True
    assert "社会保障卡补卡" not in json_out.read_text(encoding="utf-8")
    assert "社会保障卡补卡" not in markdown_out.read_text(encoding="utf-8")
