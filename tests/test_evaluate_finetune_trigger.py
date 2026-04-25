from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "evaluate_finetune_trigger.py"
    spec = importlib.util.spec_from_file_location("evaluate_finetune_trigger", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_evaluate_finetune_trigger_cli_flags_ready_when_thresholds_met(tmp_path: Path) -> None:
    mod = _load_script()
    feedback_path = tmp_path / "feedback.json"
    out_path = tmp_path / "finetune_eval.json"

    feedback_path.write_text(
        json.dumps(
            [
                {"rating": 1, "extra": {"retrieval_trace_request_id": "req-1"}},
                {"rating": 2, "extra": {"retrieval_trace_request_id": "req-2"}},
                {"rating": 4, "extra": {"retrieval_trace_request_id": "req-3"}},
                {"rating": 5, "extra": {"retrieval_trace_request_id": "req-4"}},
                {"rating": 1, "extra": {"retrieval_trace_request_id": "req-5"}},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(
        [
            "--feedback-json",
            str(feedback_path),
            "--out",
            str(out_path),
            "--min-feedback",
            "5",
            "--min-negative-feedback",
            "2",
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.finetune_trigger_eval.v1"
    assert payload["summary"]["feedback_total"] == 5
    assert payload["summary"]["negative_feedback_total"] == 3
    assert payload["summary"]["unique_requests"] == 5
    assert payload["should_trigger_finetune_eval"] is True
    assert payload["reason_codes"] == ["thresholds_met"]


def test_evaluate_finetune_trigger_cli_explains_why_thresholds_not_met(tmp_path: Path) -> None:
    mod = _load_script()
    feedback_path = tmp_path / "feedback.json"
    out_path = tmp_path / "finetune_eval.json"

    feedback_path.write_text(
        json.dumps(
            [
                {"rating": 5, "extra": {"retrieval_trace_request_id": "req-1"}},
                {"rating": 4, "extra": {"retrieval_trace_request_id": "req-2"}},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = mod.main(
        [
            "--feedback-json",
            str(feedback_path),
            "--out",
            str(out_path),
            "--min-feedback",
            "5",
            "--min-negative-feedback",
            "2",
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["should_trigger_finetune_eval"] is False
    assert "insufficient_feedback_total" in payload["reason_codes"]
    assert "insufficient_negative_feedback" in payload["reason_codes"]
