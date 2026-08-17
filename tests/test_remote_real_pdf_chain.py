import json
import sys
from pathlib import Path

import pytest

import scripts.remote_real_pdf_chain as mod


@pytest.fixture
def fixed_run_id(monkeypatch: pytest.MonkeyPatch) -> str:
    run_id = "20260816-010203"
    monkeypatch.setattr(mod.time, "strftime", lambda _fmt: run_id)
    monkeypatch.setattr(mod.time, "sleep", lambda _seconds: None)
    return run_id


def test_main_success_preserves_defaults_requests_and_report_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    download_calls: list[dict[str, object]] = []
    constructor_calls: list[dict[str, object]] = []
    requests: list[dict[str, object]] = []

    def fake_download(url: str, target: Path, timeout: int) -> dict[str, object]:
        target.write_bytes(b"pdf-data")
        call = {"url": url, "target": target, "timeout": timeout}
        download_calls.append(call)
        return {
            "url": url,
            "path": str(target),
            "bytes": 8,
            "elapsed_sec": 0.125,
            "cached": False,
        }

    class FakeLiveApi:
        def __init__(
            self,
            base_url: str,
            tenant_id: str,
            account_id: str,
            user_id: str,
            timeout: int,
        ) -> None:
            constructor_calls.append(
                {
                    "base_url": base_url,
                    "tenant_id": tenant_id,
                    "account_id": account_id,
                    "user_id": user_id,
                    "timeout": timeout,
                }
            )

        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            requests.append(
                {
                    "kind": "json",
                    "method": method,
                    "path": path,
                    "payload": payload,
                    "timeout": timeout,
                }
            )
            responses: dict[tuple[str, str], tuple[int, object]] = {
                ("POST", "/api/v1/datasets/"): (
                    200,
                    {
                        "id": "ds-1",
                    },
                ),
                ("GET", "/api/v1/documents/doc-1"): (200, {"status": "completed"}),
                (
                    "GET",
                    f"/api/v1/documents/doc-1/chunks?limit={mod.DOCUMENT_CHUNK_LIST_LIMIT}",
                ): (200, {"items": [{}, {}, {}]}),
                (
                    "GET",
                    "/api/v1/documents/doc-1/parsed-content?max_chars=50000",
                ): (200, {"markdown_content": "Parsed body"}),
                (
                    "POST",
                    "/api/v1/kg/documents/doc-1/extract?"
                    "replace_existing=true&extract_relations=false&extract_skills=false",
                ): (200, {"started": True}),
                ("GET", "/api/v1/kg/stats?dataset_id=ds-1"): (
                    200,
                    {"events": 1, "entities": 2, "links": 3},
                ),
                ("POST", "/api/v1/kg/search"): (
                    200,
                    {
                        "result": {
                            "clues": [{"id": "c-1"}, {"id": "c-2"}],
                            "events": [{"id": "e-1"}],
                        }
                    },
                ),
                ("POST", "/api/v1/chat"): (
                    200,
                    {
                        "response": "Answer body",
                        "citations": [{"id": "cite-1"}, {"id": "cite-2"}],
                    },
                ),
            }
            return (*responses[(method, path)], 0.25)

        def multipart(
            self,
            method: str,
            path: str,
            *,
            fields: dict[str, str],
            file_path: Path,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            requests.append(
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
                return 200, {"id": "doc-1"}, 0.25
            preview_counts = {
                "langchain_recursive": 4,
                "parent_child": 5,
                "semantic_sentence": 6,
                "markdown_hierarchy": 7,
            }
            return 200, {"items": [{}] * preview_counts[fields["chunk_strategy"]]}, 0.5

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "download", fake_download)
    monkeypatch.setattr(mod, "LiveApi", FakeLiveApi)
    monkeypatch.setattr(
        sys,
        "argv",
        ["remote_real_pdf_chain.py", "--pdf-url", "https://example.test/paper.pdf"],
    )

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "real-pdf-chain" / fixed_run_id).resolve()
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert download_calls == [
        {
            "url": "https://example.test/paper.pdf",
            "target": artifact_dir / "large-paper.pdf",
            "timeout": 300,
        }
    ]
    assert constructor_calls == [
        {
            "base_url": "http://127.0.0.1:8000",
            "tenant_id": mod.DEFAULT_TENANT_ID,
            "account_id": "demo",
            "user_id": "demo",
            "timeout": 5400,
        }
    ]
    assert [(call["kind"], call["method"], call["path"]) for call in requests] == [
        ("json", "POST", "/api/v1/datasets/"),
        ("multipart", "POST", "/api/v1/documents/upload"),
        ("json", "GET", "/api/v1/documents/doc-1"),
        (
            "json",
            "GET",
            f"/api/v1/documents/doc-1/chunks?limit={mod.DOCUMENT_CHUNK_LIST_LIMIT}",
        ),
        ("json", "GET", "/api/v1/documents/doc-1/parsed-content?max_chars=50000"),
        ("multipart", "POST", "/api/v1/documents/chunk-preview"),
        ("multipart", "POST", "/api/v1/documents/chunk-preview"),
        ("multipart", "POST", "/api/v1/documents/chunk-preview"),
        ("multipart", "POST", "/api/v1/documents/chunk-preview"),
        (
            "json",
            "POST",
            "/api/v1/kg/documents/doc-1/extract?replace_existing=true&extract_relations=false&extract_skills=false",
        ),
        ("json", "GET", "/api/v1/kg/stats?dataset_id=ds-1"),
        ("json", "POST", "/api/v1/kg/search"),
        ("json", "POST", "/api/v1/chat"),
        ("json", "POST", "/api/v1/chat"),
    ]
    assert requests[0]["payload"] == {
        "name": f"Real PDF Chain {fixed_run_id}",
        "description": "Large real PDF parse/chunk/kg/rag verification",
        "default_parser_backend": "magicpdf",
        "default_chunk_strategy": "langchain_recursive",
        "pipeline": {
            "governance_enabled": True,
            "governance_remove_noise_lines": True,
            "governance_unwrap_lines": True,
            "governance_drop_duplicate_paragraphs": True,
            "persist_parsed_content": True,
            "persist_parsed_content_max_chars": 900000,
            "chunk_size": 1600,
            "chunk_overlap": 160,
            "chunk_vector_enabled": True,
            "bm25_index_enabled": True,
            "kg_enabled": False,
            "event_vector_enabled": False,
            "entity_vector_enabled": False,
        },
    }
    assert requests[1]["fields"] == {
        "dataset_id": "ds-1",
        "parser_backend": "magicpdf",
        "chunk_strategy": "langchain_recursive",
        "governance_enabled": "true",
        "chunk_vector_enabled": "true",
        "bm25_index_enabled": "true",
        "kg_enabled": "false",
        "event_vector_enabled": "false",
        "entity_vector_enabled": "false",
    }
    assert [call["fields"]["chunk_strategy"] for call in requests[5:9]] == [
        "langchain_recursive",
        "parent_child",
        "semantic_sentence",
        "markdown_hierarchy",
    ]
    assert requests[9]["payload"] == {}
    assert requests[11]["payload"] == {
        "query": mod.DEFAULT_KG_QUERIES[0],
        "dataset_id": "ds-1",
    }
    assert requests[12]["payload"] == {
        "message": mod.DEFAULT_CHAT_QUESTIONS[0],
        "dataset_id": "ds-1",
        "stream": False,
        "rag_config": {
            "top_k": 6,
            "score_threshold": 0.0,
            "retrieval_mode": "hybrid",
            "use_graph": False,
            "enable_reranker": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
            "max_tokens": 700,
            "answer_mode": "extractive",
        },
    }
    assert requests[13]["payload"] == {
        "message": mod.DEFAULT_CHAT_QUESTIONS[0],
        "dataset_id": "ds-1",
        "stream": False,
        "rag_config": {
            "top_k": 6,
            "score_threshold": 0.0,
            "retrieval_mode": "hybrid",
            "use_graph": True,
            "enable_reranker": False,
            "enable_multi_query": False,
            "enable_hyde": False,
            "enable_query_decomposition": False,
            "max_tokens": 700,
            "answer_mode": "extractive",
        },
    }
    assert report["ok"] is True
    assert report["artifact_dir"] == str(artifact_dir)
    assert report["base_url"] == "http://127.0.0.1:8000"
    assert report["source"] == {
        "url": "https://example.test/paper.pdf",
        "path": str(artifact_dir / "large-paper.pdf"),
        "bytes": 8,
        "elapsed_sec": 0.125,
        "cached": False,
    }
    assert report["pdf_bytes"] == 8
    assert report["dataset_id"] == "ds-1"
    assert report["document_id"] == "doc-1"
    assert report["document_status"] == "completed"
    assert report["chunk_count"] == 3
    assert report["parsed_chars"] == len("Parsed body")
    assert report["chunk_preview"] == [
        {
            "strategy": "langchain_recursive",
            "status_code": 200,
            "elapsed_sec": 0.5,
            "chunk_count": 4,
        },
        {
            "strategy": "parent_child",
            "status_code": 200,
            "elapsed_sec": 0.5,
            "chunk_count": 5,
        },
        {
            "strategy": "semantic_sentence",
            "status_code": 200,
            "elapsed_sec": 0.5,
            "chunk_count": 6,
        },
        {
            "strategy": "markdown_hierarchy",
            "status_code": 200,
            "elapsed_sec": 0.5,
            "chunk_count": 7,
        },
    ]
    assert report["kg_extract_status"] == 200
    assert report["kg_stats_status"] == 200
    assert report["kg_search_status"] == 200
    assert report["kg_search_count"] == 2
    assert report["chat_baseline"] == {
        "status_code": 200,
        "elapsed_sec": 0.25,
        "citation_count": 2,
        "answer_preview": "Answer body",
    }
    assert report["chat_graph"] == {
        "status_code": 200,
        "elapsed_sec": 0.25,
        "citation_count": 2,
        "answer_preview": "Answer body",
    }
    assert [step["name"] for step in report["steps"]] == [
        "create_dataset",
        "upload",
        "poll_document",
        "chunks",
        "parsed_content",
        "chunk_preview:langchain_recursive",
        "chunk_preview:parent_child",
        "chunk_preview:semantic_sentence",
        "chunk_preview:markdown_hierarchy",
        "kg_extract",
        "kg_stats",
        "kg_search",
        "chat_baseline",
        "chat_graph",
    ]
    assert output == {
        "ok": True,
        "artifact_dir": str(artifact_dir),
        "dataset_id": "ds-1",
        "document_id": "doc-1",
        "chunk_count": 3,
        "kg_extract_status": 200,
        "kg_stats_status": 200,
        "kg_search_status": 200,
        "error": None,
    }


def test_main_failure_returns_nonzero_and_writes_error_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    requests: list[tuple[str, str]] = []
    pdf_path = tmp_path / "fixture.pdf"
    pdf_path.write_bytes(b"pdf-data")

    class FakeLiveApi:
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
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del payload, timeout
            requests.append((method, path))
            return 200, {"id": "ds-1"}, 0.1

        def multipart(
            self,
            method: str,
            path: str,
            *,
            fields: dict[str, str],
            file_path: Path,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del fields, file_path, timeout
            requests.append((method, path))
            return 500, {"detail": "upload failed"}, 0.2

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", FakeLiveApi)
    monkeypatch.setattr(
        sys,
        "argv",
        ["remote_real_pdf_chain.py", "--pdf-path", str(pdf_path)],
    )

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "real-pdf-chain" / fixed_run_id).resolve()
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    output = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert requests == [
        ("POST", "/api/v1/datasets/"),
        ("POST", "/api/v1/documents/upload"),
    ]
    assert report["ok"] is False
    assert report["error"] == 'upload failed: {"detail": "upload failed"}'
    assert [step["name"] for step in report["steps"]] == ["create_dataset", "upload"]
    assert "cleanup" not in report
    assert output["ok"] is False
    assert output["error"] == 'upload failed: {"detail": "upload failed"}'


def test_main_failed_document_preserves_status_in_error_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    fixed_run_id: str,
) -> None:
    pdf_path = tmp_path / "fixture.pdf"
    pdf_path.write_bytes(b"pdf-data")

    class FakeLiveApi:
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
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del payload, timeout
            if (method, path) == ("POST", "/api/v1/datasets/"):
                return 200, {"id": "ds-1"}, 0.1
            if (method, path) == ("GET", "/api/v1/documents/doc-1"):
                return 200, {"status": "failed", "error": "parse failed"}, 0.1
            raise AssertionError((method, path))

        def multipart(
            self,
            method: str,
            path: str,
            *,
            fields: dict[str, str],
            file_path: Path,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del fields, file_path, timeout
            assert (method, path) == ("POST", "/api/v1/documents/upload")
            return 200, {"id": "doc-1"}, 0.2

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "LiveApi", FakeLiveApi)
    monkeypatch.setattr(
        sys,
        "argv",
        ["remote_real_pdf_chain.py", "--pdf-path", str(pdf_path)],
    )

    rc = mod.main()

    artifact_dir = (tmp_path / "artifacts" / "real-pdf-chain" / fixed_run_id).resolve()
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    capsys.readouterr()

    assert rc == 1
    assert report["document_status"] == "failed"
    assert report["error"] == 'document did not complete: {"status": "failed", "error": "parse failed"}'


def test_perform_cleanup_delete_document_preserves_order_and_summary() -> None:
    calls: list[dict[str, object]] = []
    steps: list[dict[str, object]] = []

    class FakeLiveApi:
        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            calls.append(
                {
                    "method": method,
                    "path": path,
                    "payload": payload,
                    "timeout": timeout,
                }
            )
            responses: dict[tuple[str, str], tuple[int, object]] = {
                ("DELETE", "/api/v1/documents/doc-1"): (204, None),
                (
                    "GET",
                    "/api/v1/datasets/ds-1/documents/export?export_format=json&limit=10",
                ): (200, {"items": []}),
                ("GET", "/api/v1/kg/stats?dataset_id=ds-1"): (
                    200,
                    {"events": 0, "entities": 0, "links": 0},
                ),
                ("DELETE", "/api/v1/datasets/ds-1"): (204, None),
            }
            return (*responses[(method, path)], 0.01)

    summary = mod.perform_cleanup(
        api=FakeLiveApi(),
        steps=steps,
        dataset_id="ds-1",
        document_id="doc-1",
        cleanup_mode="delete_document",
        delete_dataset_after=True,
        timeout=900,
    )

    assert summary == {
        "mode": "delete_document",
        "delete_document_status": 204,
        "post_cleanup_document_count": 0,
        "post_cleanup_kg_stats": {"events": 0, "entities": 0, "links": 0},
        "delete_dataset_status": 204,
    }
    assert calls == [
        {
            "method": "DELETE",
            "path": "/api/v1/documents/doc-1",
            "payload": None,
            "timeout": 900,
        },
        {
            "method": "GET",
            "path": "/api/v1/datasets/ds-1/documents/export?export_format=json&limit=10",
            "payload": None,
            "timeout": 120,
        },
        {
            "method": "GET",
            "path": "/api/v1/kg/stats?dataset_id=ds-1",
            "payload": None,
            "timeout": 120,
        },
        {
            "method": "DELETE",
            "path": "/api/v1/datasets/ds-1",
            "payload": None,
            "timeout": 900,
        },
    ]
    assert [step["name"] for step in steps] == [
        "cleanup:delete_document",
        "cleanup:dataset_documents_export",
        "cleanup:kg_stats",
        "cleanup:delete_dataset",
    ]


def test_perform_cleanup_raises_when_documents_remain() -> None:
    steps: list[dict[str, object]] = []

    class FakeLiveApi:
        def json(
            self,
            method: str,
            path: str,
            *,
            payload: dict[str, object] | None = None,
            timeout: int | None = None,
        ) -> tuple[int, object, float]:
            del payload, timeout
            responses: dict[tuple[str, str], tuple[int, object]] = {
                (
                    "POST",
                    "/api/v1/datasets/ds-1/purge?dry_run=false&max_delete=1000",
                ): (200, {"deleted": 1}),
                (
                    "GET",
                    "/api/v1/datasets/ds-1/documents/export?export_format=json&limit=10",
                ): (200, {"items": [{"id": "doc-1"}]}),
            }
            return (*responses[(method, path)], 0.01)

    with pytest.raises(RuntimeError, match="documents remain after cleanup: 1"):
        mod.perform_cleanup(
            api=FakeLiveApi(),
            steps=steps,
            dataset_id="ds-1",
            document_id="doc-1",
            cleanup_mode="purge_dataset",
            delete_dataset_after=False,
            timeout=900,
        )

    assert [step["name"] for step in steps] == [
        "cleanup:purge_dataset",
        "cleanup:dataset_documents_export",
    ]
