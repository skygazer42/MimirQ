from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "mine_hard_negatives_from_traces.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("mine_hard_negatives_from_traces", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_mine_hard_negatives_uses_feedback_events_when_trace_file_has_no_match(tmp_path: Path) -> None:
    mod = _load_module()

    cases_path = tmp_path / "cases.json"
    traces_path = tmp_path / "traces.jsonl"
    feedback_path = tmp_path / "feedback.jsonl"
    out_path = tmp_path / "out.jsonl"

    question = "How do I reset my password?"
    qh = mod.stable_hash(question, length=16)  # type: ignore[attr-defined]

    cases_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.regression_cases.v1",
                "dataset_id": "ds",
                "items": [
                    {
                        "question": question,
                        "reference_sources": [{"document_id": "d_pos", "chunk_id": "c_pos"}],
                        "tags": ["feedback"],
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    traces_path.write_text(
        json.dumps(
            {
                "event": "rag_trace",
                "question_hash": "unmatched",
                "retrieval": {"retrieval_config_hash": "cfg123"},
                "citations": [{"chunk_id": "c_x", "document_id": "d_x"}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    feedback_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.training_export_row.v1",
                "source_type": "feedback",
                "question": question,
                "reference_sources": [{"document_id": "d_pos", "chunk_id": "c_pos"}],
                "trace_snapshot": {
                    "event": "rag_trace",
                    "question_hash": qh,
                    "tenant_id": "t1",
                    "retrieval": {"retrieval_config_hash": "cfg123"},
                    "citations": [
                        {"chunk_id": "c_neg_fb", "document_id": "d_fb", "relevance_score": 0.99},
                        {"chunk_id": "c_pos", "document_id": "d_pos", "relevance_score": 0.11},
                    ],
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--cases",
            str(cases_path),
            "--traces",
            str(traces_path),
            "--feedback-events",
            str(feedback_path),
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0

    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["query_hash"] == qh
    assert [it.get("chunk_id") for it in rows[0].get("hard_negatives") or []] == ["c_neg_fb"]

    dumped = json.dumps(rows[0], ensure_ascii=False, sort_keys=True)
    assert "reset my password" not in dumped


def test_mine_hard_negatives_merges_trace_and_feedback_events_with_tenant_filter(tmp_path: Path) -> None:
    mod = _load_module()

    cases_path = tmp_path / "cases.json"
    traces_path = tmp_path / "traces.jsonl"
    feedback_path = tmp_path / "feedback.jsonl"
    out_path = tmp_path / "out.jsonl"

    question = "What is the support SLA?"
    qh = mod.stable_hash(question, length=16)  # type: ignore[attr-defined]

    cases_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.regression_cases.v1",
                "dataset_id": "ds",
                "items": [
                    {
                        "question": question,
                        "reference_sources": [{"document_id": "d_pos", "chunk_id": "c_pos"}],
                        "tags": [],
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    traces_path.write_text(
        json.dumps(
            {
                "event": "rag_trace",
                "tenant_id": "t1",
                "question_hash": qh,
                "retrieval": {"retrieval_config_hash": "cfg123"},
                "citations": [
                    {"chunk_id": "c_neg_trace", "document_id": "d_t", "relevance_score": 0.97},
                    {"chunk_id": "c_pos", "document_id": "d_pos", "relevance_score": 0.12},
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    feedback_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "schema": "mimirq.training_export_row.v1",
                        "source_type": "feedback",
                        "question": question,
                        "reference_sources": [{"document_id": "d_pos", "chunk_id": "c_pos"}],
                        "trace_snapshot": {
                            "event": "rag_trace",
                            "tenant_id": "t1",
                            "question_hash": qh,
                            "retrieval": {"retrieval_config_hash": "cfg123"},
                            "citations": [
                                {"chunk_id": "c_neg_trace", "document_id": "d_t", "relevance_score": 0.96},
                                {"chunk_id": "c_neg_feedback", "document_id": "d_f", "relevance_score": 0.95},
                                {"chunk_id": "c_pos", "document_id": "d_pos", "relevance_score": 0.11},
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "schema": "mimirq.training_export_row.v1",
                        "source_type": "feedback",
                        "question": question,
                        "reference_sources": [{"document_id": "d_pos", "chunk_id": "c_pos"}],
                        "trace_snapshot": {
                            "event": "rag_trace",
                            "tenant_id": "t2",
                            "question_hash": qh,
                            "retrieval": {"retrieval_config_hash": "cfg123"},
                            "citations": [
                                {"chunk_id": "c_neg_wrong_tenant", "document_id": "d_w", "relevance_score": 0.94},
                                {"chunk_id": "c_pos", "document_id": "d_pos", "relevance_score": 0.11},
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--cases",
            str(cases_path),
            "--traces",
            str(traces_path),
            "--feedback-events",
            str(feedback_path),
            "--tenant-id",
            "t1",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0

    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1

    hard = [it.get("chunk_id") for it in rows[0].get("hard_negatives") or []]
    assert hard == ["c_neg_trace", "c_neg_feedback"]
