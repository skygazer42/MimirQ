import json

from app.rag.core.hashing import stable_hash
from scripts import mine_hard_negatives_from_traces as miner


def _write_jsonl(path, rows: list[object]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_main_merges_trace_and_feedback_negatives_without_query_text(tmp_path, capsys) -> None:
    question = "Which evidence is correct?"
    question_hash = stable_hash(question, length=16)
    cases_path = tmp_path / "cases.json"
    traces_path = tmp_path / "traces.jsonl"
    feedback_path = tmp_path / "feedback.jsonl"
    out_path = tmp_path / "hard-negatives.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "items": [
                    {
                        "question": question,
                        "reference_sources": [{"chunk_id": "positive"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        traces_path,
        [
            "ignored non-object",
            {
                "event": "rag_trace",
                "question_hash": "another-question",
                "tenant_id": "tenant-1",
                "retrieval": {"retrieval_config_hash": "cfg-1"},
                "citations": [],
            },
            {
                "event": "rag_trace",
                "question_hash": question_hash,
                "tenant_id": "tenant-1",
                "retrieval_config_hash": "cfg-1",
                "citations": [
                    {"chunk_id": "top-level-config-must-not-match", "document_id": "doc-x"},
                    {"chunk_id": "positive", "document_id": "doc-positive"},
                ],
            },
            {
                "event": "rag_trace",
                "question_hash": question_hash,
                "tenant_id": "tenant-1",
                "retrieval": {"retrieval_config_hash": "cfg-1"},
                "citations": [
                    {"chunk_id": "trace-negative", "document_id": "doc-a"},
                    {"chunk_id": "positive", "document_id": "doc-positive"},
                ],
            },
        ],
    )
    _write_jsonl(
        feedback_path,
        [
            {
                "question": question,
                "source_metadata": {"tenant_id": "tenant-1"},
                "trace_snapshot": {
                    "retrieval_config_hash": "cfg-1",
                    "citations": [
                        {"chunk_id": "feedback-negative", "document_id": "doc-b"},
                        {"chunk_id": "positive", "document_id": "doc-positive"},
                    ],
                },
            }
        ],
    )

    result = miner.main(
        [
            "--cases",
            str(cases_path),
            "--traces",
            str(traces_path),
            "--feedback-events",
            str(feedback_path),
            "--out",
            str(out_path),
            "--tenant-id",
            "tenant-1",
            "--retrieval-config-hash",
            "cfg-1",
        ]
    )

    raw_output = out_path.read_text(encoding="utf-8")
    [record] = [json.loads(line) for line in raw_output.splitlines()]
    assert result == 0
    assert question not in raw_output
    assert record["query_hash"] == question_hash
    assert [item["chunk_id"] for item in record["hard_negatives"]] == [
        "trace-negative",
        "feedback-negative",
    ]
    assert (
        capsys.readouterr().err == f"[hard-negatives] OK cases_total=1 cases_used=1 cases_skipped=0 traces_total=3 "
        f"traces_matched=1 feedback_events_total=1 feedback_events_matched=1 out={out_path}\n"
    )


def test_main_rejects_missing_feedback_events_file(tmp_path, capsys) -> None:
    cases_path = tmp_path / "cases.json"
    traces_path = tmp_path / "traces.jsonl"
    missing_feedback_path = tmp_path / "missing-feedback.jsonl"
    out_path = tmp_path / "out.jsonl"
    cases_path.write_text('{"dataset_id":"dataset-1","items":[]}', encoding="utf-8")
    traces_path.write_text("", encoding="utf-8")

    result = miner.main(
        [
            "--cases",
            str(cases_path),
            "--traces",
            str(traces_path),
            "--feedback-events",
            str(missing_feedback_path),
            "--out",
            str(out_path),
        ]
    )

    assert result == 2
    assert capsys.readouterr().err == (
        f"[hard-negatives] ERROR: feedback events file not found: {missing_feedback_path}\n"
    )
    assert not out_path.exists()


def test_main_rejects_duplicate_question_hash_without_writing_output(tmp_path, capsys) -> None:
    question = "Duplicate question"
    question_hash = stable_hash(question, length=16)
    cases_path = tmp_path / "cases.json"
    traces_path = tmp_path / "traces.jsonl"
    out_path = tmp_path / "out.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "items": [
                    {"question": question, "reference_sources": [{"chunk_id": "one"}]},
                    {"question": question, "reference_sources": [{"chunk_id": "two"}]},
                ],
            }
        ),
        encoding="utf-8",
    )
    traces_path.write_text("", encoding="utf-8")

    result = miner.main(["--cases", str(cases_path), "--traces", str(traces_path), "--out", str(out_path)])

    assert result == 2
    assert capsys.readouterr().err == f"[hard-negatives] ERROR: duplicate case question hash: {question_hash}\n"
    assert not out_path.exists()


def test_main_applies_max_cases_before_duplicate_detection(tmp_path, capsys) -> None:
    question = "Duplicate after truncation"
    cases_path = tmp_path / "cases.json"
    traces_path = tmp_path / "traces.jsonl"
    out_path = tmp_path / "out.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "items": [
                    {"question": question, "reference_sources": [{"chunk_id": "one"}]},
                    {"question": question, "reference_sources": [{"chunk_id": "two"}]},
                ],
            }
        ),
        encoding="utf-8",
    )
    traces_path.write_text("", encoding="utf-8")

    result = miner.main(
        [
            "--cases",
            str(cases_path),
            "--traces",
            str(traces_path),
            "--out",
            str(out_path),
            "--max-cases",
            "1",
        ]
    )

    assert result == 0
    assert out_path.read_text(encoding="utf-8") == ""
    assert "cases_total=1 cases_used=0 cases_skipped=1" in capsys.readouterr().err


def test_main_max_traces_limits_trace_and_feedback_streams_independently(tmp_path, capsys) -> None:
    question = "Bounded streams"
    question_hash = stable_hash(question, length=16)
    cases_path = tmp_path / "cases.json"
    traces_path = tmp_path / "traces.jsonl"
    feedback_path = tmp_path / "feedback.jsonl"
    out_path = tmp_path / "out.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "items": [
                    {"question": question, "reference_sources": [{"chunk_id": "positive"}]},
                    {"reference_sources": []},
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        traces_path,
        [
            {"event": "rag_trace", "question_hash": "not-target", "citations": []},
            {
                "event": "rag_trace",
                "question_hash": question_hash,
                "citations": [
                    {"chunk_id": "not-read", "document_id": "doc-x"},
                    {"chunk_id": "positive", "document_id": "doc-positive"},
                ],
            },
        ],
    )
    _write_jsonl(
        feedback_path,
        [
            {
                "question": question,
                "trace_snapshot": {
                    "citations": [
                        {"chunk_id": "feedback-first", "document_id": "doc-a"},
                        {"chunk_id": "positive", "document_id": "doc-positive"},
                    ]
                },
            },
            {
                "question": question,
                "trace_snapshot": {
                    "citations": [
                        {"chunk_id": "feedback-not-read", "document_id": "doc-b"},
                        {"chunk_id": "positive", "document_id": "doc-positive"},
                    ]
                },
            },
        ],
    )

    result = miner.main(
        [
            "--cases",
            str(cases_path),
            "--traces",
            str(traces_path),
            "--feedback-events",
            str(feedback_path),
            "--out",
            str(out_path),
            "--max-traces",
            "1",
        ]
    )

    [record] = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    captured = capsys.readouterr()
    assert result == 0
    assert [item["chunk_id"] for item in record["hard_negatives"]] == ["feedback-first"]
    assert "cases_total=2 cases_used=1 cases_skipped=1" in captured.err
    assert "traces_total=1 traces_matched=0 feedback_events_total=1 feedback_events_matched=1" in captured.err
