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


def test_mine_hard_negatives_from_traces_filters_by_tenant_id(tmp_path: Path) -> None:
    mod = _load_module()

    cases_path = tmp_path / "cases.json"
    traces_path = tmp_path / "traces.jsonl"
    out_path = tmp_path / "out.jsonl"

    question = "How do I reset my password?"
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

    qh = mod.stable_hash(question, length=16)  # type: ignore[attr-defined]
    # NOTE: place the "wrong tenant" trace last; without tenant filtering it would win.
    traces_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "rag_trace",
                        "tenant_id": "t1",
                        "question_hash": qh,
                        "retrieval": {"retrieval_config_hash": "cfg123"},
                        "citations": [
                            {"chunk_id": "c_neg_t1", "document_id": "d1", "relevance_score": 0.99},
                            {"chunk_id": "c_pos", "document_id": "d_pos", "relevance_score": 0.10},
                        ],
                    }
                ),
                json.dumps(
                    {
                        "event": "rag_trace",
                        "tenant_id": "t2",
                        "question_hash": qh,
                        "retrieval": {"retrieval_config_hash": "cfg123"},
                        "citations": [
                            {"chunk_id": "c_neg_t2", "document_id": "d2", "relevance_score": 0.99},
                            {"chunk_id": "c_pos", "document_id": "d_pos", "relevance_score": 0.10},
                        ],
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # New behavior: allow tenant_id filter so mining is safe in shared metrics logs.
    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--cases",
            str(cases_path),
            "--traces",
            str(traces_path),
            "--out",
            str(out_path),
            "--tenant-id",
            "t1",
        ]
    )
    assert rc == 0

    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert [h.get("chunk_id") for h in rows[0].get("hard_negatives") or []] == ["c_neg_t1"]

    dumped = json.dumps(rows[0], ensure_ascii=False, sort_keys=True)
    assert "reset my password" not in dumped
