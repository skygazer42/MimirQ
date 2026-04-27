from __future__ import annotations

import uuid

import pytest


def test_prepare_chat_cache_lookup_accepts_options(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.chat as chat_mod

    monkeypatch.setattr(chat_mod.settings, "CHAT_RESPONSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(chat_mod.settings, "CHAT_RESPONSE_CACHE_REQUIRE_EMPTY_HISTORY", True, raising=False)

    enabled, cache_key, skip_reason = chat_mod._prepare_chat_cache_lookup(
        options=chat_mod.ChatCacheLookupInput(
            db=object(),
            tenant_id=uuid.uuid4(),
            account_id="acct",
            dataset_id=None,
            document_ids=[uuid.uuid4()],
            history=[{"role": "user", "content": "seen"}],
            enable_long_term_memory=False,
            long_term_messages=[],
            enable_structured_memory=False,
            question="What changed?",
            rag_config={},
            prompt_config={},
            structured_output=False,
            structured_preset=None,
            use_graph=False,
        )
    )

    assert enabled is True
    assert cache_key is None
    assert skip_reason == "history_not_empty"


def test_build_chat_message_metadata_embeds_rewrite_docs_and_latency() -> None:
    import app.api.v1.chat as chat_mod

    out = chat_mod._build_chat_message_metadata(  # noqa: SLF001
        request_id="req-1",
        original_question="原问题",
        metrics={
            "query_for_retrieval": "重写后的问题",
            "elapsed_sec": 4.2,
            "retrieval_elapsed_sec": 1.1,
            "generation_elapsed_sec": 2.6,
        },
        citations=[
            {"document_id": "doc-1", "document_name": "手册A", "chunk_id": "c-1", "page_number": 3},
            {"document_id": "doc-2", "source": "手册B", "chunk_id": "c-2", "page_number": 4},
        ],
    )

    assert out["request_id"] == "req-1"
    assert out["rewritten_query"] == "重写后的问题"
    assert out["retrieved_docs"] == [
        {"document_id": "doc-1", "document_name": "手册A", "chunk_id": "c-1", "page_number": 3},
        {"document_id": "doc-2", "document_name": "手册B", "chunk_id": "c-2", "page_number": 4},
    ]
    assert out["latency_stats"] == {
        "elapsed_sec": 4.2,
        "retrieval_elapsed_sec": 1.1,
        "generation_elapsed_sec": 2.6,
    }


@pytest.mark.asyncio
async def test_persist_chat_stream_turn_background_accepts_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.chat as chat_mod
    import app.core.database as db_mod

    monkeypatch.setattr(chat_mod.settings, "PERSISTENT_SUMMARY_MEMORY_ENABLED", False, raising=False)
    monkeypatch.setattr(chat_mod.settings, "PERSISTENT_SUMMARY_MEMORY_AUTO_UPDATE", False, raising=False)
    monkeypatch.setattr(chat_mod.settings, "STRUCTURED_MEMORY_ENABLED", False, raising=False)

    async def _run_inline(func, /, *args, **kwargs):  # noqa: ANN001, ANN202
        return func(*args, **kwargs)

    monkeypatch.setattr(chat_mod.asyncio, "to_thread", _run_inline, raising=True)
    monkeypatch.setattr(chat_mod, "num_tokens_from_string", lambda text: len(text), raising=True)
    monkeypatch.setattr(chat_mod, "build_chat_audit_details", lambda **kwargs: kwargs, raising=True)

    cache_store: dict[str, object] = {}

    def _fake_set_cached_chat_response(key: str, payload: dict[str, object]) -> bool:
        cache_store["key"] = key
        cache_store["payload"] = payload
        return True

    monkeypatch.setattr(chat_mod, "set_cached_chat_response", _fake_set_cached_chat_response, raising=True)

    class _FakeMessage:
        def __init__(self, **kwargs):  # noqa: ANN003
            self.__dict__.update(kwargs)

    monkeypatch.setattr(chat_mod, "Message", _FakeMessage, raising=True)

    class _FakeConversation:
        def __init__(self) -> None:
            self.message_count = 0
            self.updated_at = None

    conv = _FakeConversation()
    audit_calls: list[dict[str, object]] = []

    def _fake_audit_log_event(_db, **kwargs):  # noqa: ANN001
        audit_calls.append(kwargs)

    monkeypatch.setattr(chat_mod, "audit_log_event", _fake_audit_log_event, raising=True)

    class _FakeQuery:
        def __init__(self, conversation: _FakeConversation) -> None:
            self._conversation = conversation

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def first(self) -> _FakeConversation:
            return self._conversation

    class _FakeDB:
        def __init__(self, conversation: _FakeConversation) -> None:
            self._conversation = conversation
            self.added: object | None = None
            self.committed = False
            self.closed = False

        def add(self, obj: object) -> None:
            self.added = obj

        def query(self, _model):  # noqa: ANN001
            return _FakeQuery(self._conversation)

        def commit(self) -> None:
            self.committed = True

        def close(self) -> None:
            self.closed = True

    fake_db = _FakeDB(conv)
    monkeypatch.setattr(db_mod, "SessionLocal", lambda: fake_db, raising=True)

    await chat_mod._persist_chat_stream_turn_background(
        options=chat_mod.ChatStreamPersistInput(
            tenant_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            account_id="acct",
            assistant_message_id=uuid.uuid4(),
            request_id="req-1",
            question="What changed?",
            document_count=2,
            content="Answer",
            citations=[{"document_id": "doc"}],
            metrics={"latency_ms": 12},
            dataset_id_used=uuid.uuid4(),
            cache_hit=False,
            cache_key="chat-cache-key",
            cache_eligible=True,
            structured_data={"answer": "Answer"},
            ip="127.0.0.1",
            user_agent="pytest",
            enable_summary_memory=False,
            enable_structured_memory=False,
        )
    )

    assert cache_store["key"] == "chat-cache-key"
    assert isinstance(fake_db.added, _FakeMessage)
    assert fake_db.added.message_metadata["request_id"] == "req-1"
    assert fake_db.added.message_metadata["rewritten_query"] is None
    assert fake_db.added.message_metadata["retrieved_docs"] == [{"document_id": "doc", "document_name": None, "chunk_id": None, "page_number": None}]
    assert fake_db.added.message_metadata["latency_stats"] == {"latency_ms": 12}
    assert fake_db.committed is True
    assert conv.message_count == 1
    assert len(audit_calls) == 1
