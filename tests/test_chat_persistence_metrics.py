from __future__ import annotations

from uuid import uuid4

from app.services import chat_persistence as persistence


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
        "vector_backend": "milvus",
    }

    out = persistence.finalize_chat_response_sync(
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
    )

    assert captured == []
