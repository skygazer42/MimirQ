from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "changzhou_gov_plugin_test_evidence.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("changzhou_gov_plugin_test_evidence", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_report() -> dict:
    return {
        "passed": True,
        "stages": {
            "governance": {"passed": True},
            "chunk": {"passed": True},
            "kg": {"passed": True},
        },
        "golden_draft": {
            "passed": True,
            "items_total": 20,
            "sample_questions": ["社会保障卡补卡需要什么材料？"],
        },
    }


def test_plugin_test_evidence_sanitizes_sample_questions(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = tmp_path / "raw.json"
    raw_path.write_text(json.dumps(_raw_report(), ensure_ascii=False), encoding="utf-8")

    evidence = mod.build_evidence(raw_path)
    text = json.dumps(evidence, ensure_ascii=False)
    markdown = mod.format_markdown(evidence)

    assert evidence["schema"] == "mimirq.changzhou_gov.plugin_test_evidence.v1"
    assert evidence["passed"] is True
    assert evidence["stage_count"] == 3
    assert evidence["stages"] == {"chunk": True, "governance": True, "kg": True}
    assert evidence["golden_draft"] == {"passed": True, "items_total": 20}
    assert "社会保障卡补卡需要什么材料" not in text
    assert "社会保障卡补卡需要什么材料" not in markdown


def test_plugin_test_evidence_main_writes_json_and_markdown(tmp_path: Path) -> None:
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
    assert "社会保障卡补卡需要什么材料" not in json_out.read_text(encoding="utf-8")
    assert "社会保障卡补卡需要什么材料" not in markdown_out.read_text(encoding="utf-8")
