from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "run_ltr_nightly_cycle.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("run_ltr_nightly_cycle", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_run_ltr_nightly_cycle_writes_lineage_manifest(tmp_path: Path) -> None:
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
                "dataset_id": "ds-nightly",
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
                "tenant_id": "t-nightly",
                "question_hash": qh,
                "retrieval": {"retrieval_config_hash": "cfg-nightly"},
                "citations": [
                    {"chunk_id": "c_neg", "document_id": "d_neg", "relevance_score": 0.98},
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
            "t-nightly",
        ]
    )
    assert rc == 0

    manifest_path = out_dir / "ltr_nightly_cycle.manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest.get("schema") == "mimirq.ltr_nightly_cycle_manifest.v1"
    steps = manifest.get("steps") if isinstance(manifest.get("steps"), dict) else {}
    hard_neg = steps.get("hard_negative_mining") if isinstance(steps.get("hard_negative_mining"), dict) else {}
    assert hard_neg.get("status") == "ok"
    lineage = manifest.get("lineage") if isinstance(manifest.get("lineage"), dict) else {}
    assert str(lineage.get("hard_negatives_sha256") or "").strip()
