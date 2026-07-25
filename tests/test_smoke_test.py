import json

import httpx

from scripts.smoke_test import (
    _cleanup_created_dataset,
    _core_retrieve_payload,
    _probe_web_auth_page,
    _register_for_token,
    _summarize_retrieval_evidence,
    _upload_form_data,
)


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
