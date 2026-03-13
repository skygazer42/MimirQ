from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "verify_parse_repair_gate.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("verify_parse_repair_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_verify_parse_repair_gate_passes_on_tail_shrinkage(tmp_path: Path) -> None:
    mod = _load_module()

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    out = tmp_path / "gate.json"
    baseline.write_text(
        json.dumps(
            {
                "parse_risk_summary": {
                    "parse_risk_tail": [
                        {"document_id": "doc-a"},
                        {"document_id": "doc-b"},
                        {"document_id": "doc-c"},
                    ]
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    current.write_text(
        json.dumps(
            {
                "parse_risk_summary": {
                    "parse_risk_tail": [
                        {"document_id": "doc-b"},
                    ]
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--baseline",
            str(baseline),
            "--current",
            str(current),
            "--min-shrinkage",
            "0.5",
            "--max-added-tail",
            "0",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.parse_repair_gate_report.v1"
    assert payload.get("passed") is True
    observed = payload.get("observed") if isinstance(payload.get("observed"), dict) else {}
    assert int(observed.get("baseline_tail_count") or 0) == 3
    assert int(observed.get("current_tail_count") or 0) == 1


def test_verify_parse_repair_gate_fails_when_added_tail_exceeds_limit(tmp_path: Path) -> None:
    mod = _load_module()

    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    out = tmp_path / "gate.json"
    baseline.write_text(
        json.dumps({"parse_risk_summary": {"parse_risk_tail": [{"document_id": "doc-a"}]}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    current.write_text(
        json.dumps(
            {"parse_risk_summary": {"parse_risk_tail": [{"document_id": "doc-a"}, {"document_id": "doc-new"}]}},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--baseline",
            str(baseline),
            "--current",
            str(current),
            "--min-shrinkage",
            "0.0",
            "--max-added-tail",
            "0",
            "--out",
            str(out),
        ]
    )
    assert rc == 1
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("passed") is False
    failures = payload.get("failures") if isinstance(payload.get("failures"), list) else []
    assert any("added_tail" in str(msg) for msg in failures)
