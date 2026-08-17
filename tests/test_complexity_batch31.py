import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script_module(name: str) -> Any:
    path = _repo_root() / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"test_{name}", str(path))
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def test_regression_gate_coerce_case_bundle_rejects_review_only_without_skip_import() -> None:
    mod = _load_script_module("regression_gate")
    bundle = {
        "dataset_id": "ds-1",
        "review_only": True,
        "items": [{"question": "What changed?", "dataset_id": "ds-1"}],
    }

    with pytest.raises(ValueError, match="review_only local Golden bundles cannot be imported"):
        mod.coerce_case_bundle(bundle)

    dataset_id, items = mod.coerce_case_bundle(
        bundle,
        allow_review_only=True,
    )

    assert dataset_id == "ds-1"
    assert items == [{"question": "What changed?"}]


def test_release_gate_main_returns_regression_subprocess_exit_before_http(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mod = _load_script_module("release_gate")
    budgets_path = tmp_path / "budgets.json"
    budgets_path.write_text("{}", encoding="utf-8")

    class _UnexpectedClient:
        def __init__(self, **_kwargs) -> None:
            raise AssertionError("HTTP client should not be constructed")

    monkeypatch.setattr(mod, "_run_regression_gate_subprocess", lambda **_kwargs: 2, raising=True)
    monkeypatch.setattr(mod.httpx, "Client", _UnexpectedClient, raising=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_gate.py",
            "--budgets",
            str(budgets_path),
            "--cases",
            "cases.json",
        ],
    )

    assert mod.main() == 2


def test_release_gate_main_warns_on_missing_queryset_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    mod = _load_script_module("release_gate")
    budgets_path = tmp_path / "budgets.json"
    report_path = tmp_path / "release.report.json"
    missing_snapshot = tmp_path / "missing.queryset.json"
    budgets_path.write_text("{}", encoding="utf-8")

    class _FakeClient:
        def __init__(self, **_kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_http_get_json(_client, url: str, *, headers, params=None):
        if url.endswith("/observability/slo/snapshot"):
            return {"windows": []}
        if url.endswith("/observability/rag-metrics/cost-attribution"):
            return {"rag_trace_count": 0}
        raise AssertionError(f"unexpected url: {url}")

    monkeypatch.setattr(mod.httpx, "Client", _FakeClient, raising=True)
    monkeypatch.setattr(mod, "_http_get_json", _fake_http_get_json, raising=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_gate.py",
            "--budgets",
            str(budgets_path),
            "--skip-regression",
            "--base-url",
            "http://example.test/api/v1",
            "--queryset-health-snapshot",
            str(missing_snapshot),
            "--queryset-health-policy",
            "warn",
            "--out-report",
            str(report_path),
        ],
    )

    assert mod.main() == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["violations"] == []
    assert report["queryset_health"] == {
        "path": str(missing_snapshot),
        "policy": "warn",
        "observed": {},
    }
    assert report["notes"] == [f"[release_gate] WARN: queryset health snapshot not found: {missing_snapshot}"]
    assert report["slo"] == {"snapshot": {"windows": []}}
    assert report["cost"] == {"summary": {"rag_trace_count": 0}, "computed": {}}
