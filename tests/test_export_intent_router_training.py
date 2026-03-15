from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.export_intent_router_training import export_training_rows


def test_export_training_rows_extracts_query_and_overrides() -> None:
    payload = export_training_rows(
        records=[
            {
                "question": "How to debug traceback?",
                "metrics": {
                    "retrieval_mode": "keyword",
                    "retrieval_profile": "recall20",
                    "intent_router_used": True,
                },
            }
        ]
    )
    assert payload["schema"] == "mimirq.intent_router_training.v1"
    assert int(payload["items_total"]) == 1
    items = list(payload.get("items") or [])
    assert items
    item = items[0]
    assert item["query"] == "How to debug traceback?"
    assert (item.get("label_overrides") or {}).get("retrieval_mode") == "keyword"


def test_export_training_rows_deduplicates_same_query_and_label() -> None:
    payload = export_training_rows(
        records=[
            {"query": "same query", "metrics": {"retrieval_mode": "hybrid"}},
            {"query": "same query", "metrics": {"retrieval_mode": "hybrid"}},
        ]
    )
    assert int(payload["items_total"]) == 1


def test_export_script_writes_output(tmp_path: Path) -> None:
    in_path = tmp_path / "traces.jsonl"
    out_path = tmp_path / "training.json"
    in_path.write_text(
        "\n".join(
            [
                json.dumps({"query": "q1", "metrics": {"retrieval_mode": "keyword"}}),
                json.dumps({"query": "q2", "metrics": {"retrieval_mode": "hybrid"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from os import chdir as os_chdir
    from os import getcwd

    from scripts.export_intent_router_training import main

    cwd = getcwd()
    try:
        os_chdir(tmp_path)
        code = main(["--input", "traces.jsonl", "--out", "training.json"])
    finally:
        os_chdir(cwd)
    assert code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert int(payload.get("items_total") or 0) == 2


def test_export_script_rejects_output_outside_cwd(tmp_path: Path) -> None:
    in_path = tmp_path / "traces.jsonl"
    in_path.write_text(json.dumps({"query": "q1", "metrics": {"retrieval_mode": "keyword"}}) + "\n", encoding="utf-8")
    outside_path = tmp_path.parent / "training_outside.json"

    from os import chdir as os_chdir
    from os import getcwd

    from scripts.export_intent_router_training import main

    cwd = getcwd()
    try:
        os_chdir(tmp_path)
        with pytest.raises(SystemExit):
            main(["--input", "traces.jsonl", "--out", str(outside_path)])
    finally:
        os_chdir(cwd)
