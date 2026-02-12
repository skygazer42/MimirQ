from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "regression_gate.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("regression_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_build_run_create_request_payload_includes_retrieval_overrides() -> None:
    mod = _load_module()

    payload = mod.build_run_create_request_payload(  # type: ignore[attr-defined]
        case_ids=["a", "b"],
        dataset_id="d",
        metrics=[],
        max_cases=2,
        retrieval_overrides={"retrieval_mode": "keyword", "top_k": 10, "score_threshold": 0.0},
    )
    assert payload["case_ids"] == ["a", "b"]
    assert payload["dataset_id"] == "d"
    assert payload["metrics"] == []
    assert payload["max_cases"] == 2
    assert payload["retrieval_mode"] == "keyword"
    assert payload["top_k"] == 10
    assert payload["score_threshold"] == 0.0


def test_build_run_create_request_payload_omits_none_overrides() -> None:
    mod = _load_module()

    payload = mod.build_run_create_request_payload(  # type: ignore[attr-defined]
        case_ids=["a"],
        dataset_id="d",
        metrics=["faithfulness"],
        max_cases=1,
        retrieval_overrides={"retrieval_mode": None, "top_k": None, "score_threshold": None},
    )
    assert "retrieval_mode" not in payload
    assert "top_k" not in payload
    assert "score_threshold" not in payload


def test_write_json_file_writes_trailing_newline(tmp_path: Path) -> None:
    mod = _load_module()

    out = tmp_path / "out.json"
    mod.write_json_file(out, {"a": 1})  # type: ignore[attr-defined]
    data = out.read_text(encoding="utf-8")
    assert data.endswith("\n")

