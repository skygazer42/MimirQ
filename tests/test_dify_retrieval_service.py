from uuid import uuid4

import pytest
from starlette.requests import Request


@pytest.mark.asyncio
async def test_dify_retrieval_route_passes_the_request_to_its_http_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.schemas.integrations.dify import DifyExternalKnowledgeRequest, DifyExternalKnowledgeResponse
    from app.api.v1.integrations import dify as integrations_dify
    from app.types.dify_integration import DifyActor

    seen = {}

    async def retrieve(**kwargs):
        seen.update(kwargs)
        return DifyExternalKnowledgeResponse(records=[])

    monkeypatch.setattr(integrations_dify, "_retrieve_external_knowledge", retrieve)
    request = Request({"type": "http", "headers": [(b"x-request-id", b"header-id")], "client": ("127.0.0.1", 8000)})
    request.state.request_id = "middleware-id"
    body = DifyExternalKnowledgeRequest(knowledge_id="city", query="office")
    actor = DifyActor(tenant_id=uuid4(), account_id="system:dify")
    database = object()

    response = await integrations_dify.retrieve_external_knowledge(request=request, body=body, actor=actor, db=database)

    assert response.records == []
    assert seen["body"] is body
    assert seen["actor"] is actor
    assert seen["db"] is database
    assert seen["request"] is request
    assert seen["request"].headers.get("x-request-id") == "header-id"
    assert seen["request"].state.request_id == "middleware-id"
    assert seen["request"].client.host == "127.0.0.1"


@pytest.mark.parametrize(
    ("body_id", "headers", "middleware_id", "expected"),
    [
        ("body-id", {"X-Request-ID": "header-id"}, "middleware-id", "body-id"),
        (None, {"X-Request-ID": "header-id"}, "middleware-id", "header-id"),
        (None, {}, "middleware-id", "middleware-id"),
    ],
)
def test_dify_trace_request_id_keeps_body_header_and_middleware_precedence(
    body_id, headers, middleware_id, expected
) -> None:
    from app.api.schemas.integrations.dify import DifyExternalKnowledgeRequest
    from app.services.dify import tracing

    body = DifyExternalKnowledgeRequest(knowledge_id="city", query="office", request_id=body_id)
    assert tracing._dify_trace_request_id(headers, body, request_id=middleware_id) == expected


def test_dify_trace_projects_the_shared_metadata_fields_without_losing_zero() -> None:
    from app.api.schemas.integrations import DifyExternalKnowledgeRecord
    from app.services.dify import common, tracing

    assert tracing._DIFY_TRACE_CITATION_METADATA_KEYS is common._DIFY_TRACE_CITATION_METADATA_KEYS
    metadata = {"document_id": str(uuid4()), "chunk_index": 0, "page_number": 0, "has_image": False}
    record = DifyExternalKnowledgeRecord(
        content="evidence",
        title="source",
        score=0.9,
        metadata={**metadata, "sparse_score": 0.4, "colbert_score": 0.5, "hit_type": "colbert_ann"},
    )
    trace = tracing._dify_trace_citation(record, elapsed_sec=0.0)
    assert {key: trace[key] for key in metadata} == metadata
    assert trace["retrieval_elapsed_sec"] == 0.0
    assert trace["relevance_score"] == 0.9
    assert "sparse_score" not in trace
    assert "colbert_score" not in trace
    assert "hit_type" not in trace
    record.metadata["hit_type"] = "plugin_hit"
    assert tracing._dify_trace_citation(record, elapsed_sec=0.0)["hit_type"] == "plugin_hit"


def test_dify_record_removes_retired_scores_without_dropping_public_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify import citation_records

    monkeypatch.setattr(
        citation_records.answer_hints, "_content_with_answer_hints", lambda content, _metadata, **_kwargs: content
    )
    metadata = {
        "sparse_score": 0.4,
        "colbert_score": 0.5,
        "hit_type": "colbert_ann",
        "business_field": "public-value",
        "chunk_index": 0,
    }

    record = citation_records._citation_to_dify_record(
        {"content": "evidence", "title": "source", "relevance_score": 0.9, "metadata": metadata}, dataset_id=None
    )

    assert record["metadata"] == {"business_field": "public-value", "chunk_index": 0}
    assert record["score"] == 0.9
    assert metadata["sparse_score"] == 0.4
    assert metadata["colbert_score"] == 0.5
    assert metadata["hit_type"] == "colbert_ann"
    plugin_record = citation_records._citation_to_dify_record(
        {"content": "evidence", "title": "source", "metadata": {"hit_type": "plugin_hit"}}, dataset_id=None
    )
    assert plugin_record["metadata"]["hit_type"] == "plugin_hit"


@pytest.mark.asyncio
async def test_dify_retrieval_executes_and_disabled_warmup_never_opens_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    from types import SimpleNamespace

    from app.api.schemas.integrations import DifyExternalKnowledgeRequest, DifyRetrievalSetting
    from app.api.v1.integrations import dify
    from app.services.dify import warmup
    from app.services.runtime import retrieval_limiter
    from app.types.dify_integration import DifyActor

    dataset_id = uuid4()
    for key, value in {
        "DIFY_EXTERNAL_KNOWLEDGE_MAP_JSON": json.dumps({"isolated": str(dataset_id)}),
        "DIFY_EXTERNAL_KNOWLEDGE_RESPONSE_CACHE_ENABLED": False,
        "DIFY_EXTERNAL_KNOWLEDGE_SINGLEFLIGHT_ENABLED": False,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED": False,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_PREFLIGHT_ENABLED": False,
        "DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUPPLEMENT_ENABLED": False,
        "DIFY_EXTERNAL_KNOWLEDGE_KG_ON_DEMAND_ENABLED": False,
    }.items():
        monkeypatch.setattr(dify.settings, key, value)
    calls = []

    async def citations(**kwargs):
        calls.append(kwargs)
        assert kwargs["dataset_ids"] == [dataset_id]
        return [{"chunk_content": "evidence", "document_name": "source", "relevance_score": 0.9}]

    monkeypatch.setattr(dify, "_retrieve_dataset_citations", citations)
    monkeypatch.setattr(dify, "get_readable_datasets_map", lambda *_args: {})
    monkeypatch.setattr(dify, "_dify_trace_conversation_id", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dify, "_log_dify_external_rag_trace", lambda **_kwargs: None)
    monkeypatch.setattr(retrieval_limiter, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(dify, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    request = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 8000)})
    request.state.request_id = "fixture-request"
    actor = DifyActor(tenant_id=uuid4(), account_id="system:dify")
    body = DifyExternalKnowledgeRequest(
        knowledge_id="isolated",
        query="neutral question",
        retrieval_setting=DifyRetrievalSetting(
            enable_kg_query_expansion=False,
            enable_kg_chunk_injection=False,
            enable_kg_chunk_boost=False,
        ),
    )
    result = await dify._retrieve_external_knowledge(
        request=request, body=body, actor=actor, db=SimpleNamespace(rollback=lambda: None)
    )
    assert result.records[0].content == "evidence"
    assert result.records[0].title == "source"
    assert calls and all(
        call["tenant_id"] == actor.tenant_id and call["account_id"] == actor.account_id for call in calls
    )

    def forbidden_storage():
        raise AssertionError("Disabled warmup must not open storage")

    monkeypatch.setattr(dify.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", False)
    assert (await warmup.warmup_dify_external_knowledge(db_factory=forbidden_storage))[
        "reason"
    ] == "external_knowledge_disabled"
