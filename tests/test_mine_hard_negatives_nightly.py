from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "mine_hard_negatives_nightly.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("mine_hard_negatives_nightly", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_mine_hard_negatives_nightly_writes_jsonl_and_manifest(tmp_path: Path) -> None:
    mod = _load_module()

    cases_path = tmp_path / "cases.json"
    traces_path = tmp_path / "traces.jsonl"
    out_dir = tmp_path / "nightly"

    question = "How do I reset my password?"
    qh = mod.stable_hash(question, length=16)  # type: ignore[attr-defined]

    cases_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.regression_cases.v1",
                "dataset_id": "ds1",
                "items": [
                    {
                        "question": question,
                        "reference_sources": [{"document_id": "d_pos", "chunk_id": "c_pos"}],
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
                "retrieval": {"retrieval_config_hash": "cfg-nightly"},
                "citations": [
                    {"chunk_id": "c_neg", "document_id": "d_neg", "relevance_score": 0.95},
                    {"chunk_id": "c_pos", "document_id": "d_pos", "relevance_score": 0.11},
                ],
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
            "--out-dir",
            str(out_dir),
            "--tenant-id",
            "t1",
            "--retrieval-config-hash",
            "cfg-nightly",
        ]
    )
    assert rc == 0

    out_jsonl = out_dir / "hard_negatives.nightly.jsonl"
    out_manifest = out_dir / "hard_negatives.nightly.manifest.json"
    assert out_jsonl.exists()
    assert out_manifest.exists()

    rows = [json.loads(line) for line in out_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0].get("query_hash") == qh

    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    assert manifest.get("schema") == "mimirq.hard_negatives_nightly_manifest.v1"
    assert int(manifest.get("records_written") or 0) == 1
    assert str(manifest.get("output_path") or "").endswith("hard_negatives.nightly.jsonl")
