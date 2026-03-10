from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "regression_gate.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("regression_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_regression_gate_report_includes_channel_attribution() -> None:
    mod = _load_module()

    report = mod.build_regression_gate_report(  # type: ignore[attr-defined]
        dataset_id="ds-1",
        run_id="run-1",
        matched_case_count=2,
        metrics=["retrieval_recall"],
        thresholds_enabled=True,
        ok=False,
        failures=["retrieval_recall=0.2000 < min 0.3000"],
        run_payload={"retrieval_mode": "hybrid"},
        detail={
            "run": {
                "status": "completed",
                "summary": {"retrieval_recall": 0.2},
            },
            "items": [
                {
                    "citations": [
                        {"vector_score": 0.9, "bm25_score": 0.0},
                        {"bm25_score": 0.5, "lexical_score": 0.4},
                        {"sparse_score": 0.3},
                    ]
                }
            ],
        },
    )

    assert report["gate_status"] == "fail"
    assert report["channel_attribution"]["totals"]["vector"] == 1
    assert report["channel_attribution"]["totals"]["bm25"] == 1
    assert report["channel_attribution"]["totals"]["lexical"] == 1
    assert report["channel_attribution"]["totals"]["sparse"] == 1
    assert report["channel_attribution"]["totals"]["multi"] == 1


def test_render_regression_gate_markdown_renders_summary_and_failures() -> None:
    mod = _load_module()

    markdown = mod.render_regression_gate_markdown(  # type: ignore[attr-defined]
        {
            "gate_status": "fail",
            "run_status": "completed",
            "dataset_id": "ds-1",
            "run_id": "run-1",
            "matched_case_count": 2,
            "thresholds_enabled": True,
            "summary": {"retrieval_recall": 0.2},
            "channel_attribution": {"totals": {"vector": 1, "bm25": 2, "lexical": 0, "sparse": 0, "multi": 0}},
            "failures": ["retrieval_recall=0.2000 < min 0.3000"],
        }
    )

    assert "# Retrieval Regression Gate Report" in markdown
    assert "`fail`" in markdown
    assert "| retrieval_recall | 0.2000 |" in markdown
    assert "| bm25 | 2 |" in markdown
    assert "retrieval_recall=0.2000 < min 0.3000" in markdown
