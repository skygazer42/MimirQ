from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "export_diagnostics.py"
    spec = importlib.util.spec_from_file_location("export_diagnostics", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_export_diagnostics_cli_writes_redacted_summary(tmp_path: Path) -> None:
    mod = _load_script()
    metrics_path = tmp_path / "metrics.jsonl"
    feedback_path = tmp_path / "feedback.json"
    out_path = tmp_path / "diagnostics.json"

    metrics_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "rag_done",
                        "request_id": "req-1",
                        "tenant_id": "tenant-1",
                        "route": "default",
                        "retrieval_mode": "hybrid",
                        "metrics": {"elapsed_sec": 4.0, "retrieval_elapsed_sec": 1.5},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "event": "rag_done",
                        "request_id": "req-2",
                        "tenant_id": "tenant-1",
                        "route": "default",
                        "retrieval_mode": "vector",
                        "metrics": {"elapsed_sec": 6.0, "retrieval_elapsed_sec": 2.0},
                    },
                    ensure_ascii=False,
                ),
                json.dumps({"event": "rag_trace", "request_id": "req-1", "tenant_id": "tenant-1"}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    feedback_path.write_text(
        json.dumps(
            [
                {"rating": 1, "tags": ["bad"], "reason": "用户原始投诉文本"},
                {"rating": 5, "tags": ["good"], "reason": None},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(
        [
            "--metrics-jsonl",
            str(metrics_path),
            "--feedback-json",
            str(feedback_path),
            "--out",
            str(out_path),
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.export_diagnostics.v1"
    assert payload["metrics"]["rag_done_count"] == 2
    assert payload["metrics"]["rag_trace_count"] == 1
    assert payload["metrics"]["avg_elapsed_sec"] == 5.0
    assert payload["metrics"]["avg_retrieval_elapsed_sec"] == 1.75
    assert payload["metrics"]["retrieval_mode_counts"] == {"hybrid": 1, "vector": 1}
    assert payload["feedback"]["total"] == 2
    assert payload["feedback"]["rating_counts"] == {"1": 1, "5": 1}
    assert payload["feedback"]["tag_counts"] == {"bad": 1, "good": 1}
    assert payload["feedback"]["reason_present_count"] == 1
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "req-1" not in dumped
    assert "tenant-1" not in dumped
    assert "用户原始投诉文本" not in dumped
