from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "schedule_parse_repair.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("schedule_parse_repair", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_schedule_parse_repair_merges_and_sorts_candidates(tmp_path: Path) -> None:
    mod = _load_module()

    snapshot = tmp_path / "snapshot.json"
    diff = tmp_path / "diff.json"
    out = tmp_path / "schedule.json"

    snapshot.write_text(
        json.dumps(
            {
                "parse_risk_summary": {
                    "top_low_quality_documents": [
                        {"document_id": "doc-a", "score": 0.20},
                        {"document_id": "doc-b", "score": 0.45},
                    ],
                    "parse_risk_tail": [
                        {"document_id": "doc-c", "score": 0.30},
                    ],
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    diff.write_text(
        json.dumps(
            {
                "parse_risk_tail_drift": {
                    "added_document_ids": ["doc-b", "doc-z"],
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--input",
            str(snapshot),
            "--input",
            str(diff),
            "--max-docs",
            "10",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.parse_repair_schedule.v1"
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    assert [row.get("document_id") for row in actions] == ["doc-b", "doc-z", "doc-a", "doc-c"]
    assert float(actions[0].get("risk_score") or 0.0) == pytest.approx(1.0)
    assert "parse_risk_tail_added" in list(actions[0].get("reasons") or [])


def test_schedule_parse_repair_honors_min_risk_and_max_docs(tmp_path: Path) -> None:
    mod = _load_module()

    candidates = tmp_path / "candidates.json"
    out = tmp_path / "schedule.json"
    candidates.write_text(
        json.dumps(
            {
                "candidates": [
                    {"document_id": "doc-a", "risk_score": 0.90, "reason": "manual_high"},
                    {"document_id": "doc-b", "risk_score": 0.60, "reason": "manual_mid"},
                    {"document_id": "doc-c", "risk_score": 0.20, "reason": "manual_low"},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--input",
            str(candidates),
            "--min-risk-score",
            "0.5",
            "--max-docs",
            "1",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    assert len(actions) == 1
    assert actions[0].get("document_id") == "doc-a"
