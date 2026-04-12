from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "diff_parsing_retrieval_proof_summaries.py"
    spec = importlib.util.spec_from_file_location("diff_parsing_retrieval_proof_summaries", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_diff_parsing_proof_summaries_writes_json_and_markdown(tmp_path: Path) -> None:
    mod = _load_script()
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "current.json"
    out = tmp_path / "diff.json"
    out_md = tmp_path / "diff.md"

    baseline.write_text(
        json.dumps({"hit_at_k_mean": 1.0, "mrr_mean": 1.0, "failed_case_ids": []}),
        encoding="utf-8",
    )
    current.write_text(
        json.dumps({"hit_at_k_mean": 0.9, "mrr_mean": 0.8, "failed_case_ids": ["case-a"]}),
        encoding="utf-8",
    )

    diff = mod.run(  # type: ignore[attr-defined]
        baseline_path=baseline,
        current_path=current,
        out=out,
        out_md=out_md,
    )

    assert diff["schema"] == "mimirq.parsing_retrieval_proof_diff.v1"
    assert diff["metric_deltas"]["hit_at_k_mean_delta"] == -0.1
    assert diff["metric_deltas"]["mrr_mean_delta"] == -0.2
    assert diff["failed_case_drift"]["added_ids"] == ["case-a"]
    assert out.exists()
    assert out_md.exists()


def test_parsing_proof_summary_baseline_contract_is_valid() -> None:
    payload = json.loads(Path("ci/parsing_retrieval_proof_summary_baseline.v1.json").read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.parsing_retrieval_proof_summary.v1"
    assert payload.get("hit_at_k_mean") == 1.0
    assert payload.get("mrr_mean") == 1.0
    assert payload.get("failed_case_ids") == []
