import httpx

from scripts.smoke_test import _cleanup_created_dataset, _summarize_retrieval_evidence


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
