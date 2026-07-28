
from dataclasses import replace
from uuid import uuid4

import pytest

from app.services import chat_persistence as persistence


def _base_finalize_options(
    **overrides: object,
) -> persistence.ChatResponseFinalizationInput:
    base = persistence.ChatResponseFinalizationInput(
        db=None,  # type: ignore[arg-type]
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        account_id="demo",
        assistant_message_id=uuid4(),
        request_id=uuid4().hex,
        question="What token belongs only to OBS?",
        document_count=1,
        full_response="Token OBS belongs only here.",
        citations=[{"chunk_content": "Token OBS belongs only here."}],
        metrics={
            "generation_fallback_kind": "extractive_retrieval_summary",
            "generation_fallback_reason": "explicit_extractive_answer_mode",
            "retrieval_mode": "keyword",
            "retrieval_elapsed_sec": 0.12,
            "vector_backend": "milvus",
        },
        structured_data=None,
        dataset_id_used=None,
        cache_eligible=False,
        cache_hit=False,
        cache_key=None,
        singleflight_key=None,
        singleflight_leader=False,
        request_enable_structured_memory=False,
        ip=None,
        user_agent=None,
        enable_online_eval=False,
        retrieval_mode_default="hybrid",
    )
    if not overrides:
        return base
    return replace(base, **overrides)


def test_finalize_chat_response_sync_logs_rag_trace_for_extractive_fallback(
    monkeypatch,
) -> None:
    captured: list[dict] = []
    persisted: list[dict] = []

    monkeypatch.setattr(
        persistence,
        "log_metrics",
        lambda payload: captured.append(dict(payload)),
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "store_chat_response_cache_if_needed",
        lambda **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "resolve_inflight_chat_response",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "persist_chat_turn_sync",
        lambda **kwargs: persisted.append(dict(kwargs)),
        raising=True,
    )

    tenant_id = uuid4()
    conversation_id = uuid4()
    request_id = uuid4().hex

    citations = [
        {
            "document_id": str(uuid4()),
            "chunk_id": str(uuid4()),
            "chunk_content": "Token OBS belongs only here.",
            "retrieval_elapsed_sec": 0.12,
        }
    ]
    metrics = {
        "generation_fallback_kind": "extractive_retrieval_summary",
        "generation_fallback_reason": "explicit_extractive_answer_mode",
        "retrieval_mode": "keyword",
        "retrieval_elapsed_sec": 0.12,
        "retrieval_per_query": [
            {
                "kind": "main",
                "query_chars": 31,
                "query_tokens": 7,
                "elapsed_sec": 0.12,
                "ok": True,
            }
        ],
        "vector_backend": "milvus",
    }

    out = persistence.finalize_chat_response_sync(
        options=persistence.ChatResponseFinalizationInput(
            db=None,  # type: ignore[arg-type]
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            account_id="demo",
            assistant_message_id=uuid4(),
            request_id=request_id,
            question="What token belongs only to OBS?",
            document_count=1,
            full_response="Token OBS belongs only here.",
            citations=citations,
            metrics=metrics,
            structured_data=None,
            dataset_id_used=None,
            cache_eligible=False,
            cache_hit=False,
            cache_key=None,
            singleflight_key=None,
            singleflight_leader=False,
            request_enable_structured_memory=False,
            ip=None,
            user_agent=None,
            enable_online_eval=False,
            retrieval_mode_default="hybrid",
        ),
    )

    assert out["generation_fallback_kind"] == "extractive_retrieval_summary"
    assert len(captured) == 1
    payload = captured[0]
    assert payload["event"] == "rag_trace"
    assert payload["conversation_id"] == str(conversation_id)
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["request_id"] == request_id
    assert payload["citations_count"] == 1
    assert payload["retrieval"]["mode"] == "keyword"
    assert payload["generation_fallback_reason"] == "explicit_extractive_answer_mode"
    cost = payload["cost_attribution"]
    assert cost["schema"] == "mimirq.cost_attribution.v1"
    assert cost["llm"] == {
        "model_used": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "source": "extractive_fallback",
    }
    assert cost["embeddings"] == {
        "provider": str(persistence.settings.EMBEDDING_PROVIDER or ""),
        "model": str(persistence.settings.EMBEDDING_MODEL or ""),
        "query_count": 1,
        "query_chars": 31,
        "query_tokens": 7,
        "source": "estimate",
    }
    assert cost["retrieval"] == {
        "elapsed_sec": 0.12,
        "rerank_elapsed_sec": None,
        "vector_backend": "milvus",
        "query_count": 1,
    }
    assert len(persisted) == 1


def test_finalize_chat_response_sync_skips_rag_trace_when_not_extractive_fallback(
    monkeypatch,
) -> None:
    captured: list[dict] = []

    monkeypatch.setattr(
        persistence,
        "log_metrics",
        lambda payload: captured.append(dict(payload)),
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "store_chat_response_cache_if_needed",
        lambda **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "resolve_inflight_chat_response",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "persist_chat_turn_sync",
        lambda **_kwargs: None,
        raising=True,
    )

    persistence.finalize_chat_response_sync(
        options=persistence.ChatResponseFinalizationInput(
            db=None,  # type: ignore[arg-type]
            tenant_id=uuid4(),
            conversation_id=uuid4(),
            account_id="demo",
            assistant_message_id=uuid4(),
            request_id=uuid4().hex,
            question="hello",
            document_count=0,
            full_response="world",
            citations=[],
            metrics={"retrieval_mode": "hybrid"},
            structured_data=None,
            dataset_id_used=None,
            cache_eligible=False,
            cache_hit=False,
            cache_key=None,
            singleflight_key=None,
            singleflight_leader=False,
            request_enable_structured_memory=False,
            ip=None,
            user_agent=None,
            enable_online_eval=False,
            retrieval_mode_default="hybrid",
        ),
    )

    assert captured == []


def test_extractive_fallback_cost_attribution_counts_the_main_query_when_breakdown_is_missing() -> None:
    question = "fallback retrieval query"

    cost = persistence._extractive_fallback_cost_attribution(
        metrics={"retrieval_elapsed_sec": 0.2, "vector_backend": "faiss"},
        citations=[],
        question=question,
    )

    assert cost["embeddings"]["query_count"] == 1
    assert cost["embeddings"]["query_chars"] == len(question)
    assert cost["embeddings"]["query_tokens"] > 0
    assert cost["retrieval"]["query_count"] == 1


def test_finalize_chat_response_sync_orders_persist_cache_then_resolve(
    monkeypatch,
) -> None:
    events: list[tuple[str, str]] = []

    def record_event(name: str, _label: str = "") -> None:
        events.append((name, _label))

    monkeypatch.setattr(
        persistence,
        "persist_chat_turn_sync",
        lambda **_kwargs: record_event("persist", "persist"),
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "store_chat_response_cache_if_needed",
        lambda **_kwargs: record_event("cache", ""),
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "resolve_inflight_chat_response",
        lambda *args, **kwargs: record_event("resolve", str(args[0] if args else "")),
        raising=True,
    )
    monkeypatch.setattr(persistence, "log_metrics", lambda payload: None, raising=True)

    options = _base_finalize_options(singleflight_key="sf-key", singleflight_leader=True)

    persistence.finalize_chat_response_sync(options=options)

    assert [name for name, _ in events] == ["persist", "cache", "resolve"]


def test_finalize_chat_response_sync_does_not_cache_or_resolve_when_persist_fails(
    monkeypatch,
) -> None:
    events: list[str] = []

    monkeypatch.setattr(
        persistence,
        "persist_chat_turn_sync",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("persist failed")),
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "store_chat_response_cache_if_needed",
        lambda **_kwargs: events.append("cache"),
        raising=True,
    )
    monkeypatch.setattr(
        persistence,
        "resolve_inflight_chat_response",
        lambda *_args, **_kwargs: events.append("resolve"),
        raising=True,
    )
    monkeypatch.setattr(persistence, "log_metrics", lambda payload: None, raising=True)

    options = _base_finalize_options(singleflight_key="sf-key", singleflight_leader=True)

    with pytest.raises(RuntimeError, match="persist failed"):
        persistence.finalize_chat_response_sync(options=options)

    assert events == []
