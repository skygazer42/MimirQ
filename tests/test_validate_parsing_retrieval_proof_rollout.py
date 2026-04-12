from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script():
    path = _repo_root() / "scripts" / "validate_parsing_retrieval_proof_rollout.py"
    spec = importlib.util.spec_from_file_location("validate_parsing_retrieval_proof_rollout", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_parsing_proof_rollout_contract_is_valid() -> None:
    payload = json.loads(Path("ci/parsing_retrieval_proof_rollout.v1.json").read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.parsing_retrieval_proof_rollout.v1"
    assert payload.get("current_stage") == "informational"
    assert payload.get("allowed_stages") == ["informational", "warn", "fail"]


def test_validate_parsing_proof_rollout_main_writes_normalized_output(tmp_path: Path) -> None:
    mod = _load_script()
    out = tmp_path / "rollout.normalized.json"
    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--rollout",
            "ci/parsing_retrieval_proof_rollout.v1.json",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "mimirq.parsing_retrieval_proof_rollout.v1"
    assert payload["current_stage"] == "informational"
