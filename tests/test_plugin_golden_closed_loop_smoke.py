from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "plugin_golden_closed_loop_smoke.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("plugin_golden_closed_loop_smoke", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class _FakeClient:
    def __init__(self, *, missing_metadata_summary: bool = False) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []
        self._detail_polls = 0
        self._missing_metadata_summary = missing_metadata_summary

    def json(
        self,
        method: str,
        path: str,
        *,
        payload: dict | None = None,
        query: dict | None = None,
    ) -> dict:
        self.calls.append((method, path, payload, query))

        if method == "GET" and path == "/api/v1/pipeline/plugins":
            return {
                "items": [
                    {
                        "id": "draft-only",
                        "version": "1.0.0",
                        "executable": False,
                        "refs": {"chunk": "plugin:draft-only@1.0.0:chunk"},
                        "contract": {"golden": {"enabled": True}},
                    },
                    {
                        "id": "demo-service",
                        "version": "1.0.0",
                        "published": True,
                        "executable": True,
                        "test_status": "passed",
                        "refs": {
                            "governance": "plugin:demo-service@1.0.0:governance",
                            "chunk": "plugin:demo-service@1.0.0:chunk",
                        },
                        "contract": {"golden": {"enabled": True}},
                    },
                ],
                "errors": [],
            }

        if method == "POST" and path == "/api/v1/pipeline/plugins/golden-draft/import":
            assert payload == {
                "dataset_id": "00000000-0000-0000-0000-000000000001",
                "plugin_ref": "plugin:demo-service@1.0.0:chunk",
                "max_items": 2,
                "max_chunks": 5000,
                "include_unmarked_chunks": False,
                "overwrite": False,
            }
            return {
                "draft": {
                    "items_total": 2,
                    "plugin_id": "demo-service",
                    "plugin_version": "1.0.0",
                    "plugin_ref": "plugin:demo-service@1.0.0:chunk",
                    "bundle": {
                        "items": [
                            {
                                "extra": {
                                    "expected_metadata": {"source_record_id": "a"},
                                    "plugin_package_hash": "pkg_hash_abc123",
                                }
                            },
                            {"extra": {"expected_metadata": {"source_record_id": "b"}}},
                        ]
                    },
                },
                "import_result": {
                    "created": 2,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [],
                    "case_ids": [
                        "11111111-1111-1111-1111-111111111111",
                        "22222222-2222-2222-2222-222222222222",
                    ],
                },
            }

        if method == "POST" and path == "/api/v1/evaluations/ragas/regression/runs":
            assert payload == {
                "dataset_id": "00000000-0000-0000-0000-000000000001",
                "case_ids": [
                    "11111111-1111-1111-1111-111111111111",
                    "22222222-2222-2222-2222-222222222222",
                ],
                "metrics": [],
                "use_llm_judge": False,
                "skip_empty_contexts": True,
                "max_cases": 2,
                "enable_hierarchy_recall": True,
                "hierarchy_sibling_window": 2,
                "hierarchy_overfetch_factor": 4,
            }
            return {"id": "33333333-3333-3333-3333-333333333333", "status": "queued"}

        if method == "GET" and path == "/api/v1/evaluations/ragas/regression/runs/33333333-3333-3333-3333-333333333333":
            assert query == {"include_items": "true", "include_contexts": "false"}
            self._detail_polls += 1
            if self._detail_polls == 1:
                return {"run": {"id": "33333333-3333-3333-3333-333333333333", "status": "running"}}
            summary = {"items": 2, "retrieval_recall": 1.0}
            if not self._missing_metadata_summary:
                summary.update(
                    {
                        "expected_metadata_cases_total": 2,
                        "expected_metadata_hit_rate": 1.0,
                        "expected_metadata_recall": 1.0,
                        "expected_metadata_fields_total": 2,
                        "expected_metadata_fields_matched": 2,
                    }
                )
            return {
                "run": {
                    "id": "33333333-3333-3333-3333-333333333333",
                    "status": "completed",
                    "summary": summary,
                },
                "items": [],
            }

        raise AssertionError(f"unexpected call: {method} {path}")


def test_closed_loop_imports_plugin_goldens_and_runs_retrieval_regression() -> None:
    mod = _load_module()
    client = _FakeClient()

    result = mod.run_closed_loop_smoke(  # type: ignore[attr-defined]
        client=client,
        dataset_id="00000000-0000-0000-0000-000000000001",
        plugin_ref=None,
        max_items=2,
        max_chunks=5000,
        include_unmarked_chunks=False,
        overwrite=False,
        poll_timeout_sec=1,
        poll_interval_sec=0,
    )

    assert result.plugin_ref == "plugin:demo-service@1.0.0:chunk"
    assert result.run_id == "33333333-3333-3333-3333-333333333333"
    assert result.case_ids == [
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    ]
    assert result.summary["expected_metadata_hit_rate"] == 1.0
    assert result.plugin_source == {
        "plugin_id": "demo-service",
        "plugin_version": "1.0.0",
        "plugin_ref": "plugin:demo-service@1.0.0:chunk",
        "plugin_package_hash": "pkg_hash_abc123",
        "draft_items_total": 2,
    }
    assert [call[1] for call in client.calls] == [
        "/api/v1/pipeline/plugins",
        "/api/v1/pipeline/plugins/golden-draft/import",
        "/api/v1/evaluations/ragas/regression/runs",
        "/api/v1/evaluations/ragas/regression/runs/33333333-3333-3333-3333-333333333333",
        "/api/v1/evaluations/ragas/regression/runs/33333333-3333-3333-3333-333333333333",
    ]


def test_closed_loop_requires_plugin_expected_metadata_summary() -> None:
    mod = _load_module()
    client = _FakeClient(missing_metadata_summary=True)

    with pytest.raises(RuntimeError, match="expected_metadata"):
        mod.run_closed_loop_smoke(  # type: ignore[attr-defined]
            client=client,
            dataset_id="00000000-0000-0000-0000-000000000001",
            plugin_ref=None,
            max_items=2,
            max_chunks=5000,
            include_unmarked_chunks=False,
            overwrite=False,
            poll_timeout_sec=1,
            poll_interval_sec=0,
        )


def test_closed_loop_rejects_explicit_non_chunk_plugin_ref() -> None:
    mod = _load_module()
    client = _FakeClient()

    with pytest.raises(RuntimeError, match="plugin_ref must be a registered chunk plugin ref"):
        mod.run_closed_loop_smoke(  # type: ignore[attr-defined]
            client=client,
            dataset_id="00000000-0000-0000-0000-000000000001",
            plugin_ref="plugin:demo-service@1.0.0:governance",
            max_items=2,
            max_chunks=5000,
            include_unmarked_chunks=False,
            overwrite=False,
            poll_timeout_sec=1,
            poll_interval_sec=0,
        )


def test_extract_case_ids_falls_back_to_skipped_existing_ids() -> None:
    mod = _load_module()

    import_result, case_ids = mod._extract_case_ids(  # type: ignore[attr-defined]
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
