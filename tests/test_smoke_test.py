import json
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from scripts import smoke_test
from scripts.smoke_test import (
    _build_parser,
    _cleanup_created_dataset,
    _core_retrieve_payload,
    _probe_web_auth_page,
    _register_for_token,
    _resolve_auth_headers,
    _summarize_retrieval_evidence,
    _upload_form_data,
    wait_ready,
)

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


class _ClientStub:
    def __enter__(self) -> "_ClientStub":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


class _UuidStub:
    def __init__(self, hex_value: str) -> None:
        self.hex = hex_value


def _install_main_test_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    wait_ready_impl: Callable[..., dict[str, bool]],
    detect_auth_mode_impl: Callable[..., str],
    request_with_retries_impl: Callable[..., httpx.Response],
    perf_counter_values: list[float],
    uuid_hexes: list[str] | None = None,
    wait_for_document_completion_impl: Callable[..., dict[str, str]] | None = None,
    get_system_status_impl: Callable[..., dict[str, Any]] | None = None,
) -> None:
    monkeypatch.setattr(smoke_test, "load_dotenv", lambda _path: {})
    monkeypatch.setattr(smoke_test, "wait_ready", wait_ready_impl)
    monkeypatch.setattr(smoke_test, "_detect_auth_mode", detect_auth_mode_impl)
    monkeypatch.setattr(smoke_test, "request_with_retries", request_with_retries_impl)
    monkeypatch.setattr(smoke_test.httpx, "Client", lambda **_kwargs: _ClientStub())
    perf_iter = iter(perf_counter_values)
    monkeypatch.setattr(smoke_test.time, "perf_counter", lambda: next(perf_iter))
    if uuid_hexes is not None:
        uuid_iter = iter(_UuidStub(hex_value) for hex_value in uuid_hexes)
        monkeypatch.setattr(smoke_test.uuid, "uuid4", lambda: next(uuid_iter))
    if wait_for_document_completion_impl is not None:
        monkeypatch.setattr(
            smoke_test,
            "_wait_for_document_completion",
            wait_for_document_completion_impl,
        )
    if get_system_status_impl is not None:
        monkeypatch.setattr(
            smoke_test,
            "_get_system_status_best_effort",
            get_system_status_impl,
        )


def _make_request_recorder(
    events: list[tuple[str, ...]],
    specs: list[dict[str, Any]],
) -> Callable[..., httpx.Response]:
    index = 0

    def fake_request_with_retries(
        _client: object,
        method: str,
        url: str,
        *,
        expected: set[int],
        headers: dict[str, str] | None = None,
        **kwargs: object,
    ) -> httpx.Response:
        nonlocal index
        spec = specs[index]
        index += 1
        events.append(("request", method, url))
        assert method == spec["method"]
        assert url == spec["url"]
        assert expected == spec["expected"]
        if "headers" in spec:
            assert headers == spec["headers"]
        if "json_body" in spec:
            assert kwargs["json"] == spec["json_body"]
        if "data_body" in spec:
            assert kwargs["data"] == spec["data_body"]
        file_checker = spec.get("file_checker")
        if callable(file_checker):
            file_checker(kwargs["files"])
        return spec["response"]

    return fake_request_with_retries


def test_retrieval_evidence_matches_fact_and_document_in_same_citation() -> None:
    summary = _summarize_retrieval_evidence(
        {
            "has_evidence": True,
            "citations": [
                {"document_id": "expected-doc", "chunk_content": "unrelated text"},
                {"document_id": "other-doc", "chunk_content": "launch_code=smoke-123"},
                {"document_id": "expected-doc", "chunk_content": "launch_code=smoke-123"},
            ],
        },
        document_id="expected-doc",
        marker="launch_code=smoke-123",
    )

    assert summary == {"has_evidence": True, "citation_count": 3, "matched": True}


def test_retrieval_evidence_rejects_fact_from_another_document() -> None:
    summary = _summarize_retrieval_evidence(
        {
            "has_evidence": True,
            "citations": [
                {"document_id": "expected-doc", "chunk_content": "unrelated text"},
                {"document_id": "other-doc", "chunk_content": "launch_code=smoke-123"},
            ],
        },
        document_id="expected-doc",
        marker="launch_code=smoke-123",
    )

    assert summary == {"has_evidence": True, "citation_count": 2, "matched": False}


def test_cleanup_created_dataset_purges_before_delete() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.method == "POST":
            return httpx.Response(200, json={"deleted": 1})
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = _cleanup_created_dataset(
            client,
            api_base="http://mimirq.test/api/v1",
            headers={"X-User-ID": "demo"},
            dataset_id="dataset-1",
        )

    assert calls == [
        ("POST", "http://mimirq.test/api/v1/datasets/dataset-1/purge?dry_run=false&max_delete=1000"),
        ("DELETE", "http://mimirq.test/api/v1/datasets/dataset-1"),
    ]
    assert summary == {"purged_documents": 1, "dataset_deleted": True}


def test_cleanup_created_dataset_deletes_document_before_dataset() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.method == "DELETE" and "/documents/" in str(request.url):
            return httpx.Response(204)
        if request.method == "POST":
            return httpx.Response(200, json={"deleted": 1})
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = _cleanup_created_dataset(
            client,
            api_base="http://mimirq.test/api/v1",
            headers={"X-User-ID": "demo"},
            dataset_id="dataset-1",
            document_id="document-1",
        )

    assert calls == [
        ("DELETE", "http://mimirq.test/api/v1/documents/document-1"),
        ("POST", "http://mimirq.test/api/v1/datasets/dataset-1/purge?dry_run=false&max_delete=1000"),
        ("DELETE", "http://mimirq.test/api/v1/datasets/dataset-1"),
    ]
    assert summary == {"purged_documents": 1, "dataset_deleted": True}


def test_cleanup_created_dataset_retries_delete_after_conflict() -> None:
    calls: list[tuple[str, str]] = []
    delete_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal delete_attempts
        calls.append((request.method, str(request.url)))
        if request.method == "POST":
            if len([method for method, _ in calls if method == "POST"]) == 1:
                return httpx.Response(200, json={"deleted": 0})
            return httpx.Response(200, json={"deleted": 1})
        delete_attempts += 1
        if delete_attempts == 1:
            return httpx.Response(409, json={"error": "CONFLICT", "message": "dataset still has documents"})
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = _cleanup_created_dataset(
            client,
            api_base="http://mimirq.test/api/v1",
            headers={"X-User-ID": "demo"},
            dataset_id="dataset-1",
        )

    assert calls == [
        ("POST", "http://mimirq.test/api/v1/datasets/dataset-1/purge?dry_run=false&max_delete=1000"),
        ("DELETE", "http://mimirq.test/api/v1/datasets/dataset-1"),
        ("POST", "http://mimirq.test/api/v1/datasets/dataset-1/purge?dry_run=false&max_delete=1000"),
        ("DELETE", "http://mimirq.test/api/v1/datasets/dataset-1"),
    ]
    assert summary == {"purged_documents": 1, "dataset_deleted": True}


def test_register_for_token_uses_local_bootstrap_account() -> None:
    calls: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        calls.append((request.method, str(request.url), body))
        return httpx.Response(201, json={"token": {"access_token": "jwt-token"}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        token = _register_for_token(
            client,
            api_base="http://mimirq.test/api/v1",
            email="smoke-123@example.com",
            username="smoke-123",
            password="smoke-password",
        )

    assert token == "jwt-token"
    assert calls == [
        (
            "POST",
            "http://mimirq.test/api/v1/auth/register",
            {
                "email": "smoke-123@example.com",
                "password": "smoke-password",
                "username": "smoke-123",
            },
        )
    ]


def test_resolve_auth_headers_uses_explicit_token_without_auth_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _build_parser().parse_args(["--token", "explicit-token"])
    report: dict[str, Any] = {}

    monkeypatch.setattr(
        smoke_test,
        "_detect_auth_mode",
        lambda *_args, **_kwargs: "jwt",
    )
    monkeypatch.setattr(
        smoke_test,
        "request_with_retries",
        lambda *_args, **_kwargs: pytest.fail("unexpected auth request"),
    )

    with httpx.Client() as client:
        headers = _resolve_auth_headers(
            client,
            args=args,
            dotenv={},
            api_base="http://mimirq.test/api/v1",
            tenant_id=DEFAULT_TENANT_ID,
            report=report,
        )

    assert headers == {
        "X-Tenant-ID": DEFAULT_TENANT_ID,
        "Authorization": "Bearer explicit-token",
    }
    assert report == {
        "auth_mode": "jwt",
        "headers": {"tenant": True, "user": False, "bearer": True},
    }


def test_resolve_auth_headers_logs_in_with_identifier_and_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _build_parser().parse_args(["--identifier", "demo@example.com", "--password", "secret-pass"])
    report: dict[str, Any] = {}
    calls: list[tuple[str, str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        calls.append((request.method, str(request.url), payload))
        return httpx.Response(200, json={"token": {"access_token": "login-token"}})

    monkeypatch.setattr(
        smoke_test,
        "_detect_auth_mode",
        lambda *_args, **_kwargs: "jwt",
    )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        headers = _resolve_auth_headers(
            client,
            args=args,
            dotenv={},
            api_base="http://mimirq.test/api/v1",
            tenant_id=DEFAULT_TENANT_ID,
            report=report,
        )

    assert calls == [
        (
            "POST",
            "http://mimirq.test/api/v1/auth/login",
            {"identifier": "demo@example.com", "password": "secret-pass"},
        )
    ]
    assert headers == {
        "X-Tenant-ID": DEFAULT_TENANT_ID,
        "Authorization": "Bearer login-token",
    }
    assert report == {
        "auth_mode": "jwt",
        "headers": {"tenant": True, "user": False, "bearer": True},
    }


def test_resolve_auth_headers_bootstrap_registers_temporary_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _build_parser().parse_args(["--bootstrap-register"])
    report: dict[str, Any] = {}
    calls: list[tuple[str, str, dict[str, str]]] = []
    uuid_values = iter(
        [
            _UuidStub("aaaabbbbccccddddeeeeffff11112222"),
            _UuidStub("11112222333344445555666677778888"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        calls.append((request.method, str(request.url), payload))
        return httpx.Response(201, json={"token": {"access_token": "bootstrap-token"}})

    monkeypatch.setattr(
        smoke_test,
        "_detect_auth_mode",
        lambda *_args, **_kwargs: "jwt",
    )
    monkeypatch.setattr(smoke_test.uuid, "uuid4", lambda: next(uuid_values))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        headers = _resolve_auth_headers(
            client,
            args=args,
            dotenv={},
            api_base="http://mimirq.test/api/v1",
            tenant_id=DEFAULT_TENANT_ID,
            report=report,
        )

    assert calls == [
        (
            "POST",
            "http://mimirq.test/api/v1/auth/register",
            {
                "email": "smoke-aaaabbbbcccc@example.com",
                "username": "smoke-aaaabbbbcccc",
                "password": "smoke-11112222333344445555666677778888",
            },
        )
    ]
    assert headers == {
        "X-Tenant-ID": DEFAULT_TENANT_ID,
        "Authorization": "Bearer bootstrap-token",
    }
    assert report == {
        "auth_mode": "jwt",
        "headers": {"tenant": True, "user": False, "bearer": True},
    }


def test_core_only_upload_disables_external_indexing_dependencies() -> None:
    assert _upload_form_data(dataset_id="dataset-1", parser_backend="auto", core_only=True) == {
        "dataset_id": "dataset-1",
        "parser_backend": "auto",
        "chunk_vector_enabled": "false",
        "event_vector_enabled": "false",
        "entity_vector_enabled": "false",
        "kg_enabled": "false",
    }


def test_core_only_retrieval_stays_offline() -> None:
    payload = _core_retrieve_payload(query="launch_code=test", dataset_id="dataset-1")

    assert payload["rag_config"]["retrieval_mode"] == "keyword"
    assert payload["rag_config"]["enable_reranker"] is False


def test_probe_web_auth_page_requires_login_labels() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://web.test/auth"
        return httpx.Response(200, text="<html><body>登录<label>账号</label><label>密码</label></body></html>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = _probe_web_auth_page(client, web_base="http://web.test")

    assert summary == {"status_code": 200, "labels": ["登录", "账号", "密码"]}


def test_wait_ready_retries_connection_refused_until_service_is_up(monkeypatch) -> None:
    calls: list[str] = []

    class _Response:
        status_code = 200
        content = b'{"ok": true}'

        def json(self) -> dict[str, bool]:
            return {"ok": True}

    class _Client:
        def get(self, url: str) -> _Response:
            calls.append(url)
            if len(calls) < 3:
                raise ConnectionRefusedError(111, "Connection refused")
            return _Response()

    monkeypatch.setattr("scripts.smoke_test.time.sleep", lambda *_args, **_kwargs: None)

    payload = wait_ready(
        _Client(),
        api_base="http://secondary.test/api/v1",
        timeout_sec=1.0,
        poll_interval_sec=0.0,
    )

    assert payload == {"ok": True}
    assert len(calls) == 3


def test_main_core_only_success_preserves_order_payload_output_and_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[tuple[str, ...]] = []
    out_path = tmp_path / "smoke_report.json"
    smoke_fact = "smoke-bbbbccccdddd"

    def wait_ready_impl(
        _client: object,
        *,
        api_base: str,
        timeout_sec: float,
        poll_interval_sec: float,
    ) -> dict[str, bool]:
        events.append(("ready", api_base, str(timeout_sec), str(poll_interval_sec)))
        return {"ok": True}

    def detect_auth_mode_impl(
        _client: object,
        *,
        api_base: str,
        override: str | None,
    ) -> str:
        events.append(("auth_mode", api_base, str(override)))
        return "header"

    def wait_for_document_completion_impl(
        _client: object,
        *,
        api_base: str,
        headers: dict[str, str],
        document_id: str,
        timeout_sec: float,
        poll_interval_sec: float,
        verbose: bool,
    ) -> dict[str, str]:
        events.append(
            (
                "ingest",
                api_base,
                json.dumps(headers, sort_keys=True),
                document_id,
                str(timeout_sec),
                str(poll_interval_sec),
                str(verbose),
            )
        )
        return {"status": "completed", "stage": "done", "progress": "100"}

    def check_upload_files(files: object) -> None:
        file_name, file_bytes, media_type = files["file"]  # type: ignore[index]
        assert file_name == "smoke.txt"
        assert media_type == "text/plain"
        assert f"SMOKE_FACT: launch_code={smoke_fact}".encode("utf-8") in file_bytes

    request_with_retries_impl = _make_request_recorder(
        events,
        [
            {
                "method": "POST",
                "url": "http://localhost:8000/api/v1/datasets/",
                "expected": {201},
                "headers": {"X-Tenant-ID": DEFAULT_TENANT_ID, "X-User-ID": "demo"},
                "json_body": {"name": "smoke-aaaabbbb", "description": "smoke test dataset"},
                "response": httpx.Response(201, json={"id": "dataset-1"}),
            },
            {
                "method": "POST",
                "url": "http://localhost:8000/api/v1/documents/upload",
                "expected": {201},
                "headers": {"X-Tenant-ID": DEFAULT_TENANT_ID, "X-User-ID": "demo"},
                "data_body": {
                    "dataset_id": "dataset-1",
                    "parser_backend": "auto",
                    "chunk_vector_enabled": "false",
                    "event_vector_enabled": "false",
                    "entity_vector_enabled": "false",
                    "kg_enabled": "false",
                },
                "file_checker": check_upload_files,
                "response": httpx.Response(201, json={"id": "doc-1"}),
            },
            {
                "method": "POST",
                "url": "http://localhost:8000/api/v1/rag/retrieve",
                "expected": {200},
                "headers": {"X-Tenant-ID": DEFAULT_TENANT_ID, "X-User-ID": "demo"},
                "json_body": {
                    "query": f"launch_code={smoke_fact}",
                    "dataset_id": "dataset-1",
                    "rag_config": {
                        "use_graph": False,
                        "top_k": 10,
                        "score_threshold": 0.0,
                        "retrieval_mode": "keyword",
                        "enable_reranker": False,
                        "enable_multi_query": False,
                    },
                },
                "response": httpx.Response(
                    200,
                    json={
                        "has_evidence": True,
                        "citations": [
                            {
                                "document_id": "doc-1",
                                "chunk_content": f"launch_code={smoke_fact}",
                            }
                        ],
                    },
                ),
            },
            {
                "method": "DELETE",
                "url": "http://localhost:8000/api/v1/documents/doc-1",
                "expected": {204, 404},
                "response": httpx.Response(204),
            },
            {
                "method": "POST",
                "url": "http://localhost:8000/api/v1/datasets/dataset-1/purge?dry_run=false&max_delete=1000",
                "expected": {200},
                "json_body": {},
                "response": httpx.Response(200, json={"deleted": 1}),
            },
            {
                "method": "DELETE",
                "url": "http://localhost:8000/api/v1/datasets/dataset-1",
                "expected": {204},
                "response": httpx.Response(204),
            },
        ],
    )

    _install_main_test_runtime(
        monkeypatch,
        wait_ready_impl=wait_ready_impl,
        detect_auth_mode_impl=detect_auth_mode_impl,
        request_with_retries_impl=request_with_retries_impl,
        wait_for_document_completion_impl=wait_for_document_completion_impl,
        perf_counter_values=[10.0, 10.25],
        uuid_hexes=[
            "aaaabbbbccccddddeeeeffff11112222",
            "bbbbccccddddeeeeffff111122223333",
        ],
    )

    exit_code = smoke_test.main(["--core-only", "--out", str(out_path)])

    assert exit_code == 0
    assert events == [
        ("ready", "http://localhost:8000/api/v1", "60.0", "2.0"),
        ("auth_mode", "http://localhost:8000/api/v1", "None"),
        ("request", "POST", "http://localhost:8000/api/v1/datasets/"),
        ("request", "POST", "http://localhost:8000/api/v1/documents/upload"),
        (
            "ingest",
            "http://localhost:8000/api/v1",
            '{"X-Tenant-ID": "00000000-0000-0000-0000-000000000000", "X-User-ID": "demo"}',
            "doc-1",
            "600.0",
            "2.0",
            "False",
        ),
        ("request", "POST", "http://localhost:8000/api/v1/rag/retrieve"),
        ("request", "DELETE", "http://localhost:8000/api/v1/documents/doc-1"),
        ("request", "POST", "http://localhost:8000/api/v1/datasets/dataset-1/purge?dry_run=false&max_delete=1000"),
        ("request", "DELETE", "http://localhost:8000/api/v1/datasets/dataset-1"),
    ]

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [
        "[smoke] ready: ok",
        "[smoke] auth_mode=header",
        "[smoke] dataset: created dataset-1",
        "[smoke] upload: document_id=doc-1",
        "[smoke] ingest: completed",
        "[smoke] retrieval: evidence ok",
        "[smoke] cleanup: dataset deleted",
        "[smoke] OK in 250ms",
    ]
    assert json.loads(out_path.read_text(encoding="utf-8")) == {
        "api_base": "http://localhost:8000/api/v1",
        "tenant_id": DEFAULT_TENANT_ID,
        "ready": {"ok": True},
        "auth_mode": "header",
        "headers": {"tenant": True, "user": True, "bearer": False},
        "dataset_id": "dataset-1",
        "document_id": "doc-1",
        "ingest_status": {"status": "completed", "stage": "done", "progress": "100"},
        "retrieval": {"has_evidence": True, "citation_count": 1, "matched": True},
        "cleanup": {"purged_documents": 1, "dataset_deleted": True},
        "ok": True,
        "elapsed_ms": 250,
    }


def test_main_returns_1_for_chat_validation_failure_and_writes_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[tuple[str, ...]] = []
    out_path = tmp_path / "smoke_report.json"

    def wait_ready_impl(
        _client: object,
        *,
        api_base: str,
        timeout_sec: float,
        poll_interval_sec: float,
    ) -> dict[str, bool]:
        events.append(("ready", api_base, str(timeout_sec), str(poll_interval_sec)))
        return {"ok": True}

    def detect_auth_mode_impl(
        _client: object,
        *,
        api_base: str,
        override: str | None,
    ) -> str:
        events.append(("auth_mode", api_base, str(override)))
        return "header"

    def wait_for_document_completion_impl(
        _client: object,
        *,
        api_base: str,
        headers: dict[str, str],
        document_id: str,
        timeout_sec: float,
        poll_interval_sec: float,
        verbose: bool,
    ) -> dict[str, str]:
        events.append(("ingest", api_base, document_id))
        return {"status": "completed", "stage": "done", "progress": "100"}

    def check_upload_files(files: object) -> None:
        file_name, file_bytes, media_type = files["file"]  # type: ignore[index]
        assert file_name == "smoke.txt"
        assert media_type == "text/plain"
        assert b"launch_code=smoke-bbbbccccdddd" in file_bytes

    request_with_retries_impl = _make_request_recorder(
        events,
        [
            {
                "method": "POST",
                "url": "http://localhost:8000/api/v1/datasets/",
                "expected": {201},
                "json_body": {"name": "smoke-aaaabbbb", "description": "smoke test dataset"},
                "response": httpx.Response(201, json={"id": "dataset-1"}),
            },
            {
                "method": "POST",
                "url": "http://localhost:8000/api/v1/documents/upload",
                "expected": {201},
                "file_checker": check_upload_files,
                "response": httpx.Response(201, json={"id": "doc-1"}),
            },
            {
                "method": "POST",
                "url": "http://localhost:8000/api/v1/chat",
                "expected": {200},
                "headers": {"X-Tenant-ID": DEFAULT_TENANT_ID, "X-User-ID": "demo"},
                "json_body": {
                    "message": (
                        "What is the value of launch_code in SMOKE_FACT? "
                        "Return only the structured JSON object as instructed."
                    ),
                    "dataset_id": "dataset-1",
                    "structured_output": True,
                    "structured_preset": "summary",
                    "stream": False,
                    "rag_config": {
                        "use_graph": False,
                        "top_k": 10,
                        "enable_multi_query": False,
                    },
                },
                "response": httpx.Response(200, json={"structured": False, "content": ""}),
            },
        ],
    )

    def get_system_status_impl(
        _client: object,
        *,
        api_base: str,
        headers: dict[str, str],
    ) -> dict[str, dict[str, bool]]:
        events.append(("system_status", api_base, json.dumps(headers, sort_keys=True)))
        return {"llm": {"ok": False}}

    _install_main_test_runtime(
        monkeypatch,
        wait_ready_impl=wait_ready_impl,
        detect_auth_mode_impl=detect_auth_mode_impl,
        request_with_retries_impl=request_with_retries_impl,
        wait_for_document_completion_impl=wait_for_document_completion_impl,
        get_system_status_impl=get_system_status_impl,
        perf_counter_values=[20.0, 20.5],
        uuid_hexes=[
            "aaaabbbbccccddddeeeeffff11112222",
            "bbbbccccddddeeeeffff111122223333",
        ],
    )

    exit_code = smoke_test.main(["--out", str(out_path)])

    assert exit_code == 1
    assert events == [
        ("ready", "http://localhost:8000/api/v1", "60.0", "2.0"),
        ("auth_mode", "http://localhost:8000/api/v1", "None"),
        ("request", "POST", "http://localhost:8000/api/v1/datasets/"),
        ("request", "POST", "http://localhost:8000/api/v1/documents/upload"),
        ("ingest", "http://localhost:8000/api/v1", "doc-1"),
        ("request", "POST", "http://localhost:8000/api/v1/chat"),
        (
            "system_status",
            "http://localhost:8000/api/v1",
            '{"X-Tenant-ID": "00000000-0000-0000-0000-000000000000", "X-User-ID": "demo"}',
        ),
    ]

    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "[smoke] ready: ok",
        "[smoke] auth_mode=header",
        "[smoke] dataset: created dataset-1",
        "[smoke] upload: document_id=doc-1",
        "[smoke] ingest: completed",
    ]
    assert captured.err.splitlines() == [
        (
            "[smoke] ERROR: POST http://localhost:8000/api/v1/chat failed (200): "
            "structured output validation failed. Ensure LLM is configured "
            "and that structured presets are enabled."
        ),
        f"[smoke] wrote report: {out_path}",
    ]
    assert json.loads(out_path.read_text(encoding="utf-8")) == {
        "api_base": "http://localhost:8000/api/v1",
        "tenant_id": DEFAULT_TENANT_ID,
        "ready": {"ok": True},
        "auth_mode": "header",
        "headers": {"tenant": True, "user": True, "bearer": False},
        "dataset_id": "dataset-1",
        "document_id": "doc-1",
        "ingest_status": {"status": "completed", "stage": "done", "progress": "100"},
        "chat": {
            "structured": False,
            "structured_type": None,
            "structured_preset": "summary",
            "content_chars": 0,
        },
        "system_status": {"llm": {"ok": False}},
        "ok": False,
        "error": (
            "POST http://localhost:8000/api/v1/chat failed (200): "
            "structured output validation failed. Ensure LLM is configured "
            "and that structured presets are enabled."
        ),
        "elapsed_ms": 500,
    }


def test_main_returns_2_for_unexpected_error_and_writes_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out_path = tmp_path / "smoke_report.json"
    perf_counter_values = iter([30.0, 30.4])

    class _ClientStub:
        def __enter__(self) -> "_ClientStub":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

    monkeypatch.setattr(smoke_test, "load_dotenv", lambda _path: {})
    monkeypatch.setattr(smoke_test, "wait_ready", lambda *_args, **_kwargs: {"ok": True})
    monkeypatch.setattr(smoke_test, "_detect_auth_mode", lambda *_args, **_kwargs: "bogus")
    monkeypatch.setattr(smoke_test.httpx, "Client", lambda **_kwargs: _ClientStub())
    monkeypatch.setattr(smoke_test.time, "perf_counter", lambda: next(perf_counter_values))

    exit_code = smoke_test.main(["--out", str(out_path)])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["[smoke] ready: ok"]
    assert captured.err.splitlines() == [
        "[smoke] ERROR: unsupported auth_mode: bogus",
        f"[smoke] wrote report: {out_path}",
    ]
    assert json.loads(out_path.read_text(encoding="utf-8")) == {
        "api_base": "http://localhost:8000/api/v1",
        "tenant_id": DEFAULT_TENANT_ID,
        "ready": {"ok": True},
        "ok": False,
        "error": "unsupported auth_mode: bogus",
        "elapsed_ms": 399,
    }
