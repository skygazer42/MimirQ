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


def test_run_sample_retrieval_benchmark_writes_stable_report(tmp_path: Path) -> None:
    mod = _load_script("scripts/run_sample_retrieval_benchmark.py")
    out_path = tmp_path / "sample_bench.json"
    fixture = _repo_root() / "data" / "sample" / "retrieval_fixture_v1.json"

    rc = mod.main(["--fixture", str(fixture), "--out", str(out_path), "--retrieval-mode", "keyword", "--top-k", "5"])
    assert rc == 0
    assert out_path.exists()

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.sample_retrieval_benchmark.v1"
    summary = payload.get("summary") or {}
    assert int(summary.get("cases_total") or 0) >= 1
    assert 0.0 <= float(summary.get("hit_at_k") or 0.0) <= 1.0
    assert 0.0 <= float(summary.get("mrr") or 0.0) <= 1.0
    assert 0.0 <= float(summary.get("ndcg_at_k") or 0.0) <= 1.0
    assert 0.0 <= float(summary.get("family_hit_at_k") or 0.0) <= 1.0
    assert 0.0 <= float(summary.get("family_mrr") or 0.0) <= 1.0
    assert 0.0 <= float(summary.get("family_ndcg_at_k") or 0.0) <= 1.0
    assert float(summary.get("distinct_families_mean") or 0.0) >= 1.0

    cases = payload.get("cases") or []
    assert isinstance(cases, list) and cases
    c0 = cases[0] if isinstance(cases[0], dict) else {}
    assert "ranked_family_keys" in c0
    assert int(c0.get("distinct_families") or 0) >= 1
    assert 0.0 <= float(c0.get("top_family_share") or 0.0) <= 1.0


def test_run_sample_retrieval_benchmark_respects_llm_mock_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mod = _load_script("scripts/run_sample_retrieval_benchmark.py")
    out_path = tmp_path / "sample_bench.json"
    fixture = _repo_root() / "data" / "sample" / "retrieval_fixture_v1.json"

    monkeypatch.setenv("LLM_MOCK_ENABLED", "true")
    rc = mod.main(["--fixture", str(fixture), "--out", str(out_path)])
    assert rc == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload.get("llm_mock") is True
    assert str(payload.get("llm_mock_env") or "").lower() == "true"


def test_run_sample_retrieval_benchmark_supports_sparse_runtime_flags(tmp_path: Path) -> None:
    mod = _load_script("scripts/run_sample_retrieval_benchmark.py")
    out_path = tmp_path / "sample_bench_sparse.json"
    fixture = _repo_root() / "data" / "sample" / "retrieval_fixture_sparse_v1.json"

    rc = mod.main(
        [
            "--fixture",
            str(fixture),
            "--out",
            str(out_path),
            "--retrieval-mode",
            "keyword",
            "--top-k",
            "5",
            "--enable-sparse-retrieval",
            "--sparse-retrieval-provider",
            "deterministic",
        ]
    )
    assert rc == 0

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    runtime = payload.get("runtime") or {}
    assert runtime.get("sparse_retrieval_enabled") is True
    assert runtime.get("sparse_retrieval_provider") == "deterministic"
