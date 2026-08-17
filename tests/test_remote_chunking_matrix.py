import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.remote_chunking_matrix as mod


@pytest.fixture
def fixed_run_id(monkeypatch: pytest.MonkeyPatch) -> str:
    run_id = "20260816-010203"
    monkeypatch.setattr(mod.time, "strftime", lambda _fmt: run_id)
    return run_id


def test_cleanup_dataset_preserves_request_order_and_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, object] | None]] = []
    recorded_steps: list[str] = []

    class _Api:
        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
        ) -> SimpleNamespace:
            calls.append((method, path, payload))
            bodies = {
                (
                    "POST",
                    "/api/v1/datasets/ds-1/purge?dry_run=false&max_delete=2000",
                ): {"deleted": 3},
                (
                    "GET",
                    "/api/v1/datasets/ds-1/documents/export?export_format=json&limit=50",
                ): {"items": []},
                ("DELETE", "/api/v1/datasets/ds-1"): {},
            }
            return SimpleNamespace(
                status=204 if method == "DELETE" else 200,
                body=bodies[(method, path)],
                elapsed_sec=0.01,
            )

    monkeypatch.setattr(
        mod,
        "record_step",
        lambda _steps, name, _resp, **_extra: recorded_steps.append(name),
    )
    monkeypatch.setattr(
        mod,
        "ensure_success",
        lambda name, resp: None if 200 <= int(resp.status) < 300 else (_ for _ in ()).throw(RuntimeError(name)),
    )

    summary = mod.cleanup_dataset(_Api(), steps=[], dataset_id="ds-1")

    assert summary == {
        "dataset_id": "ds-1",
        "purge_deleted": 3,
        "delete_dataset_status": 204,
    }
    assert calls == [
        ("POST", "/api/v1/datasets/ds-1/purge?dry_run=false&max_delete=2000", {}),
        (
            "GET",
            "/api/v1/datasets/ds-1/documents/export?export_format=json&limit=50",
            None,
        ),
        ("DELETE", "/api/v1/datasets/ds-1", None),
    ]
    assert recorded_steps == [
        "cleanup:purge:ds-1",
        "cleanup:export:ds-1",
        "cleanup:delete_dataset:ds-1",
    ]


def test_main_success_preserves_cli_defaults_requests_and_report_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    file_path = tmp_path / "fixtures" / "chunking-handbook.md"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("chunking fixture", encoding="utf-8")
    artifact_dir = tmp_path / "artifacts"

    api_inits: list[tuple[str, str, str, str, int]] = []
    api_calls: list[dict[str, object]] = []
    wait_calls: list[dict[str, object]] = []

    case = {
        "name": "markdown_handbook",
        "file_type": "md",
        "path": file_path,
        "parser_backend": "auto",
        "persist_chunk_strategy": "langchain_recursive",
        "preview_strategies": ["separator", "parent_child"],
        "preview_include_chunks": False,
        "min_chunks": 1,
        "min_parsed_chars": 10,
    }

    class _Api:
        def __init__(
            self,
            base_url: str,
            tenant_id: str,
            account_id: str,
            user_id: str,
            timeout: int,
        ) -> None:
            api_inits.append((base_url, tenant_id, account_id, user_id, timeout))

        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
        ) -> SimpleNamespace:
            api_calls.append({"kind": "json", "method": method, "path": path, "payload": payload})
            bodies = {
                ("GET", "/api/v1/health"): {},
                (
                    "POST",
                    "/api/v1/datasets/",
                ): {"id": "ds-1"},
                ("GET", "/api/v1/documents/doc-1"): {
                    "status": "completed",
                    "total_characters": 42,
                    "metadata": {
                        "chunking_stats": {"count": 1},
                        "chunk_coverage": {"coverage_ratio": 0.95},
                    },
                },
                (
                    "GET",
                    f"/api/v1/documents/doc-1/chunks?limit={mod.DOCUMENT_CHUNK_LIST_LIMIT}",
                ): {
                    "items": [
                        {
                            "content": "Persisted chunk",
                            "metadata": {
                                "chunk_strategy": "langchain_recursive",
                            },
                        }
                    ],
                    "total": 1,
                },
                ("GET", "/api/v1/documents/doc-1/parsed-content?max_chars=25000"): {
                    "parsed_text": "Parsed body",
                },
                ("GET", "/api/v1/datasets/ds-1/profile/summary"): {
                    "total_documents": 1,
                    "chunk_count_histogram": [1],
                    "avg_chunk_chars_histogram": [1],
                    "chunk_length_histogram": [1],
                    "chunk_coverage_histogram": [1],
                    "chunk_overlap_waste_histogram": [1],
                    "by_file_type": {"md": 1},
                },
                (
                    "POST",
                    "/api/v1/datasets/ds-1/purge?dry_run=false&max_delete=2000",
                ): {"deleted": 1},
                (
                    "GET",
                    "/api/v1/datasets/ds-1/documents/export?export_format=json&limit=50",
                ): {"items": []},
                ("DELETE", "/api/v1/datasets/ds-1"): {},
            }
            return SimpleNamespace(
                status=204 if method == "DELETE" else 200,
                body=bodies[(method, path)],
                elapsed_sec=0.25,
            )

        def multipart(
            self,
            method: str,
            path: str,
            *,
            fields: dict[str, str],
            file_path: Path,
            timeout: int | None = None,
        ) -> SimpleNamespace:
            api_calls.append(
                {
                    "kind": "multipart",
                    "method": method,
                    "path": path,
                    "fields": fields,
                    "file_path": file_path,
                    "timeout": timeout,
                }
            )
            if path == "/api/v1/documents/upload":
                return SimpleNamespace(
                    status=200,
                    body={"id": "doc-1"},
                    elapsed_sec=0.25,
                )
            previews = {
                "separator": {
                    "total_chunks": 0,
                    "total_chunks_full": 7,
                    "stats": {
                        "avg": 88,
                        "coverage_ratio": 0.9,
                        "overlap_waste_ratio": 0.1,
                    },
                    "quality_gate": {"grade": "A"},
                    "chunks_truncated": False,
                    "parse_cache_hit": True,
                },
                "parent_child": {
                    "total_chunks": 0,
                    "total_chunks_full": 5,
                    "stats": {
                        "avg": 77,
                        "coverage_ratio": 0.8,
                        "overlap_waste_ratio": 0.2,
                    },
                    "quality_gate": {"grade": "B"},
                    "chunks_truncated": False,
                    "parse_cache_hit": False,
                },
            }
            return SimpleNamespace(
                status=200,
                body=previews[fields["chunk_strategy"]],
                elapsed_sec=0.5,
            )

    monkeypatch.setattr(mod, "LiveApi", _Api)
    monkeypatch.setattr(mod, "prepare_fixture_files", lambda _path: [case])
    monkeypatch.setattr(
        mod,
        "record_step",
        lambda steps, name, _resp, **extra: steps.append({"name": name, **extra}),
    )
    monkeypatch.setattr(
        mod,
        "wait_for_document_completed",
        lambda _api, *, steps, filename, document_id, poll_timeout: (
            wait_calls.append(
                {
                    "steps": steps,
                    "filename": filename,
                    "document_id": document_id,
                    "poll_timeout": poll_timeout,
                }
            )
            or {
                "status": "completed",
                "total_characters": 40,
                "metadata": {
                    "chunking_stats": {"count": 1},
                    "chunk_coverage": {"coverage_ratio": 0.8},
                },
            }
        ),
    )
    monkeypatch.setattr(
        mod,
        "parsed_text_from_response",
        lambda body: str((body or {}).get("parsed_text") or ""),
    )
    monkeypatch.setattr(
        mod,
        "ensure_success",
        lambda name, resp: None if 200 <= int(resp.status) < 300 else (_ for _ in ()).throw(RuntimeError(name)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["remote_chunking_matrix.py", "--artifact-dir", str(artifact_dir)],
    )

    rc = mod.main()

    assert rc == 0
    output = json.loads(capsys.readouterr().out)
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))

    assert api_inits == [
        (
            "http://127.0.0.1:8000",
            mod.DEFAULT_TENANT_ID,
            "demo",
            "demo",
            900,
        )
    ]
    assert wait_calls == [
        {
            "steps": report["steps"],
            "filename": "markdown_handbook",
            "document_id": "doc-1",
            "poll_timeout": 3600,
        }
    ]
    assert api_calls == [
        {"kind": "json", "method": "GET", "path": "/api/v1/health", "payload": None},
        {
            "kind": "json",
            "method": "POST",
            "path": "/api/v1/datasets/",
            "payload": {
                "name": f"Chunking Matrix {fixed_run_id}",
                "description": "Chunking breadth verification on real parsed outputs.",
                "permission": "all_team_members",
                "default_parser_backend": "auto",
                "default_chunk_strategy": "langchain_recursive",
                "pipeline": {
                    "governance_enabled": True,
                    "persist_parsed_content": True,
                    "persist_parsed_content_max_chars": 400000,
                    "chunk_size": 1200,
                    "chunk_overlap": 120,
                    "chunk_vector_enabled": True,
                    "bm25_index_enabled": True,
                    "kg_enabled": False,
                    "event_vector_enabled": False,
                    "entity_vector_enabled": False,
                },
            },
        },
        {
            "kind": "multipart",
            "method": "POST",
            "path": "/api/v1/documents/upload",
            "fields": {
                "dataset_id": "ds-1",
                "parser_backend": "auto",
                "chunk_strategy": "langchain_recursive",
                "governance_enabled": "true",
                "chunk_vector_enabled": "true",
                "bm25_index_enabled": "true",
                "kg_enabled": "false",
                "event_vector_enabled": "false",
                "entity_vector_enabled": "false",
            },
            "file_path": file_path,
            "timeout": None,
        },
        {
            "kind": "json",
            "method": "GET",
            "path": "/api/v1/documents/doc-1",
            "payload": None,
        },
        {
            "kind": "json",
            "method": "GET",
            "path": f"/api/v1/documents/doc-1/chunks?limit={mod.DOCUMENT_CHUNK_LIST_LIMIT}",
            "payload": None,
        },
        {
            "kind": "json",
            "method": "GET",
            "path": "/api/v1/documents/doc-1/parsed-content?max_chars=25000",
            "payload": None,
        },
        {
            "kind": "multipart",
            "method": "POST",
            "path": "/api/v1/documents/chunk-preview",
            "fields": {
                "parser_backend": "auto",
                "chunk_strategy": "separator",
                "chunk_size": "1200",
                "chunk_overlap": "120",
                "include_original_text": "false",
                "include_chunks": "false",
                "use_parse_cache": "true",
                "max_chunks": "0",
                "separator_preset": "paragraph",
                "keep_separator": "true",
                "separator_max_chunk_size": "0",
            },
            "file_path": file_path,
            "timeout": 900,
        },
        {
            "kind": "multipart",
            "method": "POST",
            "path": "/api/v1/documents/chunk-preview",
            "fields": {
                "parser_backend": "auto",
                "chunk_strategy": "parent_child",
                "chunk_size": "1200",
                "chunk_overlap": "120",
                "include_original_text": "false",
                "include_chunks": "false",
                "use_parse_cache": "true",
                "max_chunks": "0",
                "child_ratio": "0.5",
                "min_child_size": "240",
            },
            "file_path": file_path,
            "timeout": 900,
        },
        {
            "kind": "json",
            "method": "GET",
            "path": "/api/v1/datasets/ds-1/profile/summary",
            "payload": None,
        },
        {
            "kind": "json",
            "method": "POST",
            "path": "/api/v1/datasets/ds-1/purge?dry_run=false&max_delete=2000",
            "payload": {},
        },
        {
            "kind": "json",
            "method": "GET",
            "path": "/api/v1/datasets/ds-1/documents/export?export_format=json&limit=50",
            "payload": None,
        },
        {
            "kind": "json",
            "method": "DELETE",
            "path": "/api/v1/datasets/ds-1",
            "payload": None,
        },
    ]
    assert output == {
        "ok": True,
        "artifact_dir": str(artifact_dir.resolve()),
        "dataset_id": "ds-1",
    }
    assert set(report) == {
        "ok",
        "artifact_dir",
        "base_url",
        "dataset_id",
        "persisted_cases",
        "preview_checks",
        "profile_summary",
        "cleanup",
        "failures",
        "steps",
    }
    assert report["ok"] is True
    assert report["cleanup"] == {
        "dataset_id": "ds-1",
        "purge_deleted": 1,
        "delete_dataset_status": 204,
    }
    assert list(report["profile_summary"]) == [
        "total_documents",
        "chunk_count_histogram_bins",
        "avg_chunk_chars_histogram_bins",
        "chunk_length_histogram_bins",
        "chunk_coverage_histogram_bins",
        "chunk_overlap_waste_histogram_bins",
        "by_file_type",
        "failures",
    ]
    assert report["failures"] == []
    assert [step["name"] for step in report["steps"]] == [
        "health",
        "create_dataset",
        "upload:markdown_handbook",
        "detail:markdown_handbook",
        "chunks:markdown_handbook",
        "parsed:markdown_handbook",
        "preview:markdown_handbook:separator",
        "preview:markdown_handbook:parent_child",
        "profile:summary",
        "cleanup:purge:ds-1",
        "cleanup:export:ds-1",
        "cleanup:delete_dataset:ds-1",
    ]


def test_main_returns_nonzero_and_records_cleanup_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_dir = tmp_path / "artifacts"

    class _Api:
        def __init__(
            self,
            _base_url: str,
            _tenant_id: str,
            _account_id: str,
            _user_id: str,
            _timeout: int,
        ) -> None:
            pass

        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
        ) -> SimpleNamespace:
            bodies = {
                ("GET", "/api/v1/health"): {},
                ("POST", "/api/v1/datasets/"): {"id": "ds-2"},
                ("GET", "/api/v1/datasets/ds-2/profile/summary"): {
                    "total_documents": 0,
                    "chunk_count_histogram": [1],
                    "avg_chunk_chars_histogram": [1],
                    "chunk_length_histogram": [1],
                    "chunk_coverage_histogram": [1],
                    "chunk_overlap_waste_histogram": [1],
                    "by_file_type": {},
                },
            }
            return SimpleNamespace(
                status=200,
                body=bodies[(method, path)],
                elapsed_sec=0.01,
            )

    monkeypatch.setattr(mod, "LiveApi", _Api)
    monkeypatch.setattr(mod, "prepare_fixture_files", lambda _path: [])
    monkeypatch.setattr(
        mod,
        "record_step",
        lambda steps, name, _resp, **extra: steps.append({"name": name, **extra}),
    )
    monkeypatch.setattr(
        mod,
        "ensure_success",
        lambda name, resp: None if 200 <= int(resp.status) < 300 else (_ for _ in ()).throw(RuntimeError(name)),
    )
    monkeypatch.setattr(
        mod,
        "cleanup_dataset",
        lambda _api, *, steps, dataset_id: (
            steps.append({"name": f"cleanup:attempt:{dataset_id}"})
            or (_ for _ in ()).throw(RuntimeError("cleanup exploded"))
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["remote_chunking_matrix.py", "--artifact-dir", str(artifact_dir)],
    )

    rc = mod.main()

    assert rc == 1
    output = json.loads(capsys.readouterr().out)
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))

    assert output == {
        "ok": False,
        "artifact_dir": str(artifact_dir.resolve()),
        "dataset_id": "ds-2",
    }
    assert report["ok"] is False
    assert report["cleanup"] == {
        "dataset_id": "ds-2",
        "error": "cleanup exploded",
    }
    assert report["failures"] == ["cleanup: cleanup exploded"]
    assert [step["name"] for step in report["steps"]] == [
        "health",
        "create_dataset",
        "profile:summary",
        "cleanup:attempt:ds-2",
    ]
