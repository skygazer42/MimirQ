from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


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


class _Response:
    def __init__(self, body: dict) -> None:
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def post(self, url: str, *, json: dict) -> _Response:
        self.calls.append(("POST", url, json, None))
        if url.endswith("/pipeline/plugins/golden-draft/import"):
            return _Response(
                {
                    "draft": {
                        "plugin_id": "demo-service",
                        "plugin_version": "1.0.0",
                        "plugin_ref": "plugin:demo-service@1.0.0:chunk",
                        "items_total": 2,
                        "bundle": {
                            "items": [
                                {"extra": {"plugin_package_hash": "pkg_hash_abc123"}},
                            ]
                        },
                    },
                    "import_result": {
                        "created": 2,
                        "updated": 0,
                        "skipped": 0,
                        "errors": [],
                        "case_ids": ["case-a", "case-b"],
                    },
                }
            )
        if url.endswith("/evaluations/ragas/regression/runs"):
            assert json["dataset_id"] == "00000000-0000-0000-0000-000000000001"
            assert json["case_ids"] == ["case-a", "case-b"]
            assert json["max_cases"] == 2
            return _Response({"id": "run-1"})
        raise AssertionError(f"unexpected POST {url}")

    def get(self, url: str, *, params: dict | None = None) -> _Response:
        self.calls.append(("GET", url, None, params))
        if "/evaluations/ragas/regression/cases" in url:
            raise AssertionError("plugin Golden gate should use returned case_ids without listing cases")
        if url.endswith("/evaluations/ragas/regression/runs/run-1"):
            return _Response(
                {
                    "run": {
                        "id": "run-1",
                        "status": "completed",
                        "summary": {
                            "items": 2,
                            "expected_metadata_hit_rate": 1.0,
                            "expected_metadata_recall": 1.0,
                        },
                    }
                }
            )
        raise AssertionError(f"unexpected GET {url}")


def test_regression_gate_can_use_plugin_golden_import_as_case_source(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    fake_client = _FakeClient()
    report_path = tmp_path / "gate-report.json"

    monkeypatch.setattr(mod.httpx, "Client", lambda **_kwargs: fake_client, raising=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "regression_gate.py",
            "--base-url",
            "http://api.test/api/v1",
            "--user-id",
            "tester",
            "--dataset-id",
            "00000000-0000-0000-0000-000000000001",
            "--plugin-golden-ref",
            "plugin:demo-service@1.0.0:chunk",
            "--out-report-json",
            str(report_path),
        ],
        )
    assert mod.main() == 0

    assert fake_client.calls[0] == (
        "POST",
        "http://api.test/api/v1/pipeline/plugins/golden-draft/import",
        {
            "dataset_id": "00000000-0000-0000-0000-000000000001",
            "plugin_ref": "plugin:demo-service@1.0.0:chunk",
            "max_items": 500,
            "max_chunks": 5000,
            "include_unmarked_chunks": False,
            "overwrite": False,
        },
        None,
    )
    assert fake_client.calls[1][0:2] == (
        "POST",
        "http://api.test/api/v1/evaluations/ragas/regression/runs",
    )

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["case_source"]["kind"] == "plugin_golden"
    assert report["case_source"]["plugin_ref"] == "plugin:demo-service@1.0.0:chunk"
    assert report["case_source"]["plugin_id"] == "demo-service"
    assert report["case_source"]["plugin_version"] == "1.0.0"
    assert report["case_source"]["plugin_package_hash"] == "pkg_hash_abc123"
    assert report["case_source"]["draft_items_total"] == 2
    assert report["case_source"]["import_result"]["created"] == 2
    assert report["case_source"]["import_result"]["case_ids"] == ["case-a", "case-b"]


def test_regression_gate_rejects_plugin_golden_thresholds_from_different_package(monkeypatch, tmp_path: Path) -> None:
    mod = _load_module()
    fake_client = _FakeClient()
    thresholds_path = tmp_path / "thresholds.json"
    thresholds_path.write_text(
        json.dumps(
            {
                "schema": "mimirq.thresholds.v2",
                "dataset_id": "00000000-0000-0000-0000-000000000001",
                "case_source": {
                    "kind": "plugin_golden",
                    "plugin_ref": "plugin:demo-service@1.0.0:chunk",
                    "plugin_package_hash": "pkg_hash_old",
                },
                "metrics": {"expected_metadata_hit_rate": {"min": 1.0}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod.httpx, "Client", lambda **_kwargs: fake_client, raising=True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "regression_gate.py",
            "--base-url",
            "http://api.test/api/v1",
            "--user-id",
            "tester",
            "--dataset-id",
            "00000000-0000-0000-0000-000000000001",
            "--plugin-golden-ref",
            "plugin:demo-service@1.0.0:chunk",
            "--metrics",
            "",
            "--thresholds",
            str(thresholds_path),
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        mod.main()

    assert excinfo.value.code == 2
    assert [call[1] for call in fake_client.calls] == [
        "http://api.test/api/v1/pipeline/plugins/golden-draft/import",
    ]


def test_plugin_golden_import_case_ids_fallback_includes_skipped_existing_ids() -> None:
    mod = _load_module()

    import_result, case_ids = mod.extract_plugin_golden_import_case_ids(  # type: ignore[attr-defined]
        {
            "draft": {"items_total": 3},
            "import_result": {
                "created": 1,
                "updated": 1,
                "skipped": 1,
                "errors": [],
                "created_case_ids": ["created-a"],
                "updated_case_ids": ["updated-a"],
                "skipped_case_ids": ["skipped-a"],
            },
        }
    )

    assert import_result["skipped"] == 1
    assert case_ids == ["created-a", "updated-a", "skipped-a"]


def test_regression_gate_rejects_non_chunk_plugin_golden_ref() -> None:
    mod = _load_module()

    with pytest.raises(ValueError, match="plugin_golden_ref must be a registered chunk plugin ref"):
        mod.build_plugin_golden_import_payload(  # type: ignore[attr-defined]
            dataset_id="00000000-0000-0000-0000-000000000001",
            plugin_ref="plugin:demo-service@1.0.0:governance",
            max_items=500,
            max_chunks=5000,
            include_unmarked_chunks=False,
            overwrite=False,
        )
