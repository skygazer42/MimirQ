from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel: str):
    path = _repo_root() / rel
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_colbert_retrieval_fixture_contract_is_valid() -> None:
    payload = json.loads(Path("data/sample/retrieval_fixture_colbert_v1.json").read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.sample_retrieval_fixture.v1"
    defaults = payload.get("defaults") if isinstance(payload.get("defaults"), dict) else {}
    assert str(defaults.get("retrieval_mode") or "").strip().lower() == "vector"
    assert bool(defaults.get("colbert_retrieval_enabled")) is True
    assert str(defaults.get("colbert_retrieval_provider") or "").strip().lower() == "deterministic"
    assert isinstance(payload.get("documents"), list)
    assert isinstance(payload.get("queries"), list)


def test_sample_benchmark_can_run_with_colbert_fixture(tmp_path: Path) -> None:
    mod = _load_script("scripts/run_sample_retrieval_benchmark.py")
    fixture = Path("data/sample/retrieval_fixture_colbert_v1.json")
    out_path = tmp_path / "colbert_bench.json"

    rc = mod.main(
        [
            "--fixture",
            str(fixture),
            "--out",
            str(out_path),
            "--enable-colbert-retrieval",
            "--colbert-retrieval-provider",
            "deterministic",
        ]
    )

    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    runtime = payload.get("runtime") if isinstance(payload.get("runtime"), dict) else {}
    assert runtime.get("colbert_retrieval_enabled") is True
    assert runtime.get("colbert_retrieval_provider") == "deterministic"
    assert payload.get("summary", {}).get("hit_at_k") == pytest.approx(1.0)
