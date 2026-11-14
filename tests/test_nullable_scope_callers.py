from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from app.api.schemas.chat import ChatRequest
from app.api.v1 import chat as chat_api
from app.api.v1 import rag
from app.rag.kg import pipeline
from app.rag.kg.search.cache import build_kg_community_summary_cache_key
from app.rag.kg.search.config import SearchConfig
from app.rag.kg.search.searcher import _community_scope
from app.rag.retrieval.orchestration.kg_query_expansion import search_kg_query_async
from app.rag.retrieval.orchestration.query_contracts import KGQueryRequest, KGQueryScope
from app.rag.retrieval.orchestration.query_planning import _deterministic_and_kg_request
from app.services.chat_stream_orchestrator import _build_stream_persist_input


@pytest.mark.parametrize("document_ids", [None, [], [uuid4()]])
def test_query_plan_preserves_document_selection_even_with_kg_disabled(document_ids) -> None:
    dataset = uuid4()
    request = SimpleNamespace(
        prepared=SimpleNamespace(query="policy"),
        routing=SimpleNamespace(
            effective_options={
                "tenant_id": uuid4(),
                "account_id": "reader",
                "dataset_id": dataset,
                "document_ids": document_ids,
                "enable_query_alias_expansion": False,
                "enable_kg_query_expansion": False,
            }
        ),
    )
    _deterministic, _aliases, kg_request = _deterministic_and_kg_request(request)
    assert kg_request.scope.document_ids == (None if document_ids is None else tuple(document_ids))
    assert kg_request.scope.dataset_id == (dataset if document_ids is None else None)


@pytest.mark.parametrize("document_ids", [None, (), (uuid4(),)])
@pytest.mark.asyncio
async def test_kg_query_transport_preserves_nullable_and_empty_scopes(document_ids, monkeypatch) -> None:
    captured = {}

    async def search(**kwargs):
        captured.update(kwargs)
        return {"events": []}

    monkeypatch.setattr(pipeline, "kg_search", search)
    await search_kg_query_async(KGQueryRequest("policy", KGQueryScope(uuid4(), "reader", document_ids)))
    assert captured["document_ids"] == (None if document_ids is None else list(document_ids))
    assert captured["account_id"] == "reader"


@pytest.mark.parametrize("cache_hit", [True, False])
@pytest.mark.parametrize("document_ids", [None, [uuid4(), uuid4()]])
def test_stream_persistence_counts_only_explicitly_selected_documents(document_ids, cache_hit) -> None:
    request = ChatRequest(message="policy", dataset_id=uuid4())
    value = _build_stream_persist_input(
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        account_id="reader",
        assistant_message_id=uuid4(),
        request_id="request",
        request=request,
        doc_ids_to_use=document_ids,
        dataset_id_used=request.dataset_id,
        cache_hit=cache_hit,
        cache_key=None,
        client_ip=None,
        user_agent=None,
        enable_summary_memory=False,
        enable_structured_memory=False,
    )
    assert value.document_count == (0 if document_ids is None else len(document_ids))


@pytest.mark.parametrize("document_ids", [None, [], [uuid4() for _ in range(205)]])
def test_capsule_creation_keeps_the_actual_optional_scope(document_ids, monkeypatch) -> None:
    monkeypatch.setattr(rag.settings, "RAG_EVIDENCE_CAPSULE_ENABLED", True)
    capsule = rag._build_evidence_capsule_payload(
        query_for_retrieval="policy",
        citations=[],
        metrics={},
        retrieval_trace_payload=None,
        query_debug=None,
        tenant_id=uuid4(),
        scope_dataset_id=uuid4(),
        scope_dataset_ids=[],
        scope_document_ids=document_ids,
        selected_pass="primary",
    )
    assert capsule is not None
    assert capsule["request_context"]["document_ids"] == (
        None if document_ids is None else [str(value) for value in document_ids[:200]]
    )


def test_community_cache_caller_preserves_the_new_scope_discriminator() -> None:
    args = dict(query="policy", tenant_id=uuid4(), dataset_id=uuid4(), account_id="reader")
    open_scope = _community_scope(
        config=SearchConfig(**args, document_ids=None), community_id="community", query="policy", report={}
    )
    empty_scope = _community_scope(
        config=SearchConfig(**args, document_ids=[]), community_id="community", query="policy", report={}
    )
    assert build_kg_community_summary_cache_key(**open_scope) != build_kg_community_summary_cache_key(**empty_scope)


@pytest.mark.parametrize("document_ids", [None, [uuid4()]])
@pytest.mark.asyncio
async def test_dataset_chat_reaches_response_finalization_with_nullable_scope(document_ids, monkeypatch) -> None:
    request = ChatRequest(message="policy", dataset_id=uuid4(), enable_summary_memory=False)
    conversation = uuid4()
    captured = {}
    runtime = SimpleNamespace(
        effective_rag_config=request.rag_config,
        dataset_id_used=request.dataset_id,
        history_for_llm=[],
        dataset_rag_defaults_applied_fields=[],
        effective_prompt_template_id=None,
        effective_prompt_template_key=None,
        effective_prompt_ab_experiment_key=None,
        dataset_prompt_defaults_applied_fields=[],
        dataset_rag_config_template_defaults_applied_fields=[],
        rag_config_template_meta=None,
    )

    async def quota(**_kwargs):
        return {}

    async def cache_state(*, options):
        assert options.document_ids is document_ids
        return SimpleNamespace(
            cache_feature_enabled=True,
            cache_key="cache",
            cache_skip_reason=None,
            cache_eligible=True,
            cache_hit=True,
            singleflight_hit=False,
            singleflight_leader=False,
            singleflight_key=None,
            full_response="answer",
            citations_data=[],
            metrics_data={"retrieval_mode": "hybrid", "vector_backend": "milvus"},
            structured_data=None,
        )

    def finalize(*, options):
        captured["count"] = options.document_count
        return options.metrics

    monkeypatch.setattr("app.services.tenant_quota_service.enforce_tenant_qps_quota_async", quota)
    monkeypatch.setattr(chat_api, "check_chat_assistant_token_quota", lambda *_args, **_kwargs: {"enabled": False})
    monkeypatch.setattr(
        chat_api,
        "_prepare_chat_turn_session",
        lambda **_kwargs: SimpleNamespace(
            conversation_id=conversation,
            scope_dataset_id=request.dataset_id,
            allowed_doc_ids=document_ids,
            long_term_messages=[],
        ),
    )
    monkeypatch.setattr(chat_api, "_prepare_chat_request_runtime", lambda **_kwargs: runtime)
    monkeypatch.setattr(chat_api, "_prepare_non_streaming_chat_cache_state", cache_state)
    monkeypatch.setattr(chat_api, "_apply_chat_runtime_metrics_context", lambda metrics, **_kwargs: metrics)
    monkeypatch.setattr(chat_api, "_finalize_chat_response_sync", finalize)
    monkeypatch.setattr(chat_api, "_maybe_schedule_summary_update", lambda **_kwargs: None)
    monkeypatch.setattr(chat_api, "num_tokens_from_string", lambda _text: 1)
    result = await chat_api.chat(
        SimpleNamespace(state=SimpleNamespace(request_id="request"), client=None, headers={}),
        request,
        BackgroundTasks(),
        tenant_id=uuid4(),
        account_id="reader",
        db=SimpleNamespace(),
    )
    assert captured["count"] == (0 if document_ids is None else len(document_ids))
    assert result["content"] == "answer"
