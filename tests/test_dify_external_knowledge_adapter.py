from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_dify_retrieval_maps_knowledge_id_to_multiple_datasets(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    token = "dify-test-token"
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    calls: list[tuple[uuid.UUID, str, int, float]] = []

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", token, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON",
        f'{{"sales-all": ["{dataset_a}", "{dataset_b}"]}}',
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "system:dify", raising=False)

    async def _fake_retrieve_dataset_citations(**kwargs):  # noqa: ANN003, ANN202
        dataset_id = kwargs["dataset_id"]
        calls.append((dataset_id, kwargs["query"], kwargs["top_k"], kwargs["score_threshold"]))
        if dataset_id == dataset_a:
            return [
                {
                    "chunk_content": "A lower-ranked sales policy chunk",
                    "relevance_score": 0.42,
                    "document_name": "sales-a.md",
                    "document_id": str(uuid.uuid4()),
                    "chunk_id": str(uuid.uuid4()),
                    "page_number": 3,
                }
            ]
        return [
            {
                "chunk_content": "B top-ranked sales policy chunk",
                "retrieval_score": 0.91,
                "document_name": "sales-b.md",
                "document_id": str(uuid.uuid4()),
                "chunk_id": str(uuid.uuid4()),
                "header_path": "Pricing / Exceptions",
            }
        ]

    monkeypatch.setattr(dify_api, "_retrieve_dataset_citations", _fake_retrieve_dataset_citations, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    res = client.post(
        "/api/v1/integrations/dify/retrieval",
        headers=_auth(token),
        json={
            "knowledge_id": "sales-all",
            "query": "报价例外条件",
            "retrieval_setting": {"top_k": 2, "score_threshold": 0.35},
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert [call[0] for call in calls] == [dataset_a, dataset_b]
    assert all(call[1] == "报价例外条件" for call in calls)
    assert all(call[2] == 2 for call in calls)
    assert all(call[3] == pytest.approx(0.35) for call in calls)
    assert [record["content"] for record in body["records"]] == [
        "B top-ranked sales policy chunk",
        "A lower-ranked sales policy chunk",
    ]
    assert body["records"][0]["score"] == pytest.approx(0.91)
    assert body["records"][0]["title"] == "sales-b.md"
    assert body["records"][0]["metadata"]["dataset_id"] == str(dataset_b)
    assert body["records"][0]["metadata"]["header_path"] == "Pricing / Exceptions"
    assert body["records"][0]["metadata"] is not None


def test_dify_retrieval_rejects_missing_or_wrong_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(dify_api.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", "expected-token", raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.include_router(dify_api.router, prefix="/api/v1/integrations/dify")
    client = TestClient(app)

    payload = {
        "knowledge_id": str(uuid.uuid4()),
        "query": "test",
        "retrieval_setting": {"top_k": 1, "score_threshold": 0.0},
    }
    missing = client.post("/api/v1/integrations/dify/retrieval", json=payload)
    wrong = client.post("/api/v1/integrations/dify/retrieval", headers=_auth("wrong-token"), json=payload)

    assert missing.status_code == 401
    assert missing.json() == {"error_code": 1001, "error_msg": "Invalid Dify Authorization header"}
    assert wrong.status_code == 401
    assert wrong.json() == {"error_code": 1002, "error_msg": "Invalid Dify API key"}


def test_dify_metadata_condition_is_converted_to_mimirq_filter() -> None:
    from app.api.v1.integrations_dify import _metadata_condition_to_filter
    from app.rag.core.filters import match_metadata_filter

    metadata_filter = _metadata_condition_to_filter(
        {
            "logical_operator": "or",
            "conditions": [
                {"name": "category", "comparison_operator": "is", "value": "contract"},
                {"name": "tags", "comparison_operator": "contains", "value": "pricing"},
                {"name": "page", "comparison_operator": "≥", "value": 3},
            ],
        }
    )

    assert metadata_filter == {
        "$or": [
            {"category": {"$eq": "contract"}},
            {"tags": {"$contains": "pricing"}},
            {"page": {"$gte": 3}},
        ]
    }
    assert match_metadata_filter({"category": "contract"}, metadata_filter)
    assert match_metadata_filter({"tags": ["sales-pricing"]}, metadata_filter)
    assert match_metadata_filter({"page": 4}, metadata_filter)
    assert not match_metadata_filter({"category": "faq", "tags": ["ops"], "page": 2}, metadata_filter)


def test_dify_record_conversion_keeps_metadata_object_and_clamps_score() -> None:
    from app.api.v1.integrations_dify import _citation_to_dify_record

    record = _citation_to_dify_record(
        {
            "content": "fallback content",
            "relevance_score": 1.7,
            "document_name": "",
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "page_number": 9,
            "metadata": None,
        },
        dataset_id=uuid.UUID("00000000-0000-0000-0000-000000000123"),
    )

    assert record["content"] == "fallback content"
    assert record["score"] == 1.0
    assert record["title"] == "doc-1"
    assert record["metadata"] == {
        "dataset_id": "00000000-0000-0000-0000-000000000123",
        "document_id": "doc-1",
        "chunk_id": "chunk-1",
        "page_number": 9,
    }
