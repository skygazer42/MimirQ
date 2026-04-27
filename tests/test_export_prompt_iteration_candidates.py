from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "export_prompt_iteration_candidates.py"
    spec = importlib.util.spec_from_file_location("export_prompt_iteration_candidates", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_export_prompt_iteration_candidates_writes_monthly_bad_case_summary(tmp_path: Path) -> None:
    mod = _load_script()
    feedback_path = tmp_path / "feedback.json"
    out_path = tmp_path / "prompt_iteration.json"

    feedback_path.write_text(
        json.dumps(
            [
                {
                    "rating": 1,
                    "reason": "答非所问",
                    "tags": ["answer_wrong"],
                    "extra": {
                        "retrieval_trace_request_id": "req-1",
                        "rag_config_snapshot": {"retrieval_mode": "hybrid"},
                    },
                    "message": {
                        "content": "原始回答 1",
                        "message_metadata": {"rewritten_query": "485 总线掉线 原因"},
                    },
                },
                {
                    "rating": 1,
                    "reason": "没有按步骤回答",
                    "tags": ["answer_wrong"],
                    "extra": {
                        "retrieval_trace_request_id": "req-2",
                        "rag_config_snapshot": {"retrieval_mode": "hybrid"},
                    },
                    "message": {
                        "content": "原始回答 2",
                        "message_metadata": {"rewritten_query": "MQTT 配置 步骤"},
                    },
                },
                {
                    "rating": 1,
                    "reason": "知识库里没有这个型号",
                    "tags": ["out_of_scope"],
                    "extra": {
                        "retrieval_trace_request_id": "req-3",
                        "rag_config_snapshot": {"retrieval_mode": "vector"},
                    },
                    "message": {
                        "content": "原始回答 3",
                        "message_metadata": {"rewritten_query": "X200 型号 接线"},
                    },
                },
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
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.prompt_iteration_candidates.v1"
    assert payload["summary"]["negative_feedback_count"] == 3
    assert payload["summary"]["groups_count"] == 2
    assert payload["groups"][0]["group_key"] == "answer_wrong"
    assert payload["groups"][0]["count"] == 2
    assert payload["groups"][0]["suggested_prompt_action"] == "tighten_stepwise_grounded_answering"
    assert payload["groups"][1]["group_key"] == "out_of_scope"
    assert payload["groups"][1]["suggested_prompt_action"] == "strengthen_out_of_scope_refusal_language"
    dumped = json.dumps(payload, ensure_ascii=False)
    assert "原始回答 1" not in dumped
    assert "req-1" not in dumped
