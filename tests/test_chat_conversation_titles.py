from types import SimpleNamespace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from fastapi import HTTPException

import app.models.chat  # noqa: F401
from app.api.schemas.chat import ChatRequest, ConversationUpdate
from app.api.v1 import chat as chat_mod
from app.models.chat import Conversation, Message


def _conversation(*, tenant_id, title, title_source):
    return Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        title=title,
        title_source=title_source,
        document_ids=[],
        message_count=0,
    )


def test_apply_auto_conversation_title_updates_auto_titles():
    tenant_id = uuid4()
    conversation = _conversation(
        tenant_id=tenant_id,
        title="Old title",
        title_source=chat_mod.CONVERSATION_TITLE_SOURCE_AUTO,
    )

    chat_mod._apply_auto_conversation_title(
        conversation,
        "Latest user question about launch codes and retrieval history",
    )

    assert conversation.title == "Latest user question about launch codes and retrie..."
    assert conversation.title_source == chat_mod.CONVERSATION_TITLE_SOURCE_AUTO


def test_apply_auto_conversation_title_preserves_manual_titles():
    tenant_id = uuid4()
    conversation = _conversation(
        tenant_id=tenant_id,
        title="Pinned title",
        title_source=chat_mod.CONVERSATION_TITLE_SOURCE_MANUAL,
    )

    chat_mod._apply_auto_conversation_title(
        conversation,
        "A newer message should not overwrite the manual title",
    )

    assert conversation.title == "Pinned title"
    assert conversation.title_source == chat_mod.CONVERSATION_TITLE_SOURCE_MANUAL


@pytest.mark.asyncio
async def test_update_conversation_marks_manual_and_blank_title_reverts_to_auto(pg_session, monkeypatch):
    tenant_id = uuid4()
    conversation = _conversation(
        tenant_id=tenant_id,
        title="Original auto title",
        title_source=chat_mod.CONVERSATION_TITLE_SOURCE_AUTO,
    )
    pg_session.add(conversation)
    pg_session.add(
        Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            content="Newest stored user question",
        )
    )
    pg_session.commit()

    monkeypatch.setattr(chat_mod.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(chat_mod, "_ensure_conversation_access", lambda *_a, **_k: None, raising=True)

    updated = await chat_mod.update_conversation(
        conversation.id,
        ConversationUpdate(title="Pinned title"),
        tenant_id=tenant_id,
        account_id="user-1",
        db=pg_session,
    )
    assert updated.title == "Pinned title"
    assert updated.title_source == chat_mod.CONVERSATION_TITLE_SOURCE_MANUAL

    reverted = await chat_mod.update_conversation(
        conversation.id,
        ConversationUpdate(title=""),
        tenant_id=tenant_id,
        account_id="user-1",
        db=pg_session,
    )
    assert reverted.title == "Newest stored user question"
    assert reverted.title_source == chat_mod.CONVERSATION_TITLE_SOURCE_AUTO


@pytest.mark.asyncio
async def test_chat_updates_existing_auto_conversation_title(pg_session, monkeypatch):
    tenant_id = uuid4()
    conversation = _conversation(
        tenant_id=tenant_id,
        title="First question",
        title_source=chat_mod.CONVERSATION_TITLE_SOURCE_AUTO,
    )
    pg_session.add(conversation)
    pg_session.commit()

    monkeypatch.setattr(chat_mod.settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)
    monkeypatch.setattr(chat_mod, "check_chat_assistant_token_quota", lambda *_a, **_k: {"enabled": False}, raising=True)
    monkeypatch.setattr(chat_mod, "_prepare_chat_cache_lookup", lambda **_k: (False, None, None), raising=True)
    monkeypatch.setattr(chat_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

    class _DummyEngine:
        async def stream_chat(self, **_kwargs):
            yield {"type": "token", "data": {"content": "assistant reply"}}
            yield {"type": "done", "data": {"metrics": {}, "structured_data": None}}

    monkeypatch.setattr(chat_mod, "get_rag_engine", lambda: _DummyEngine(), raising=True)

    import app.services.tenant_quota_service as tenant_quota_service

    monkeypatch.setattr(tenant_quota_service, "enforce_tenant_qps_quota", lambda **_k: {"enabled": False}, raising=True)

    response = await chat_mod.chat(
        http_request=SimpleNamespace(
            state=SimpleNamespace(request_id="req-1"),
            headers={},
            client=SimpleNamespace(host="127.0.0.1"),
        ),
        request=ChatRequest(
            conversation_id=conversation.id,
            message="Latest user question",
            stream=False,
        ),
        background_tasks=BackgroundTasks(),
        tenant_id=tenant_id,
        account_id="user-1",
        db=pg_session,
    )

    pg_session.refresh(conversation)

    assert response["conversation_id"] == conversation.id
    assert conversation.title == "Latest user question"
    assert conversation.title_source == chat_mod.CONVERSATION_TITLE_SOURCE_AUTO


@pytest.mark.asyncio
async def test_get_conversation_messages_allows_missing_bound_documents_and_prunes(pg_session, monkeypatch):
    tenant_id = uuid4()
    missing_doc_id = uuid4()
    original_updated_at = datetime(2026, 4, 10, 2, 3, 42, tzinfo=UTC)
    conversation = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Old bound history",
        title_source=chat_mod.CONVERSATION_TITLE_SOURCE_AUTO,
        document_ids=[missing_doc_id],
        message_count=2,
        updated_at=original_updated_at,
    )
    pg_session.add(conversation)
    pg_session.add(
        Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            content="hello",
        )
    )
    pg_session.add(
        Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="assistant",
            content="world",
        )
    )
    pg_session.commit()

    monkeypatch.setattr(chat_mod.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    payload = await chat_mod.get_conversation_messages(
        conversation.id,
        limit=20,
        before=None,
        tenant_id=tenant_id,
        account_id="user-1",
        db=pg_session,
    )

    pg_session.refresh(conversation)

    assert payload["returned"] == 2
    assert {(message.role, message.content) for message in payload["messages"]} == {
        ("user", "hello"),
        ("assistant", "world"),
    }
    assert conversation.document_ids == []
    assert conversation.updated_at == original_updated_at


@pytest.mark.asyncio
async def test_list_conversations_keeps_history_when_bound_documents_are_missing(pg_session, monkeypatch):
    tenant_id = uuid4()
    missing_doc_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Missing doc history",
        title_source=chat_mod.CONVERSATION_TITLE_SOURCE_AUTO,
        document_ids=[missing_doc_id],
        message_count=1,
    )
    pg_session.add(conversation)
    pg_session.add(
        Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            content="hello",
        )
    )
    pg_session.commit()

    monkeypatch.setattr(chat_mod.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    payload = await chat_mod.list_conversations(
        skip=0,
        limit=20,
        tenant_id=tenant_id,
        account_id="user-1",
        db=pg_session,
    )

    returned_ids = {item["id"] for item in payload["items"]}
    assert conversation.id in returned_ids


@pytest.mark.asyncio
async def test_list_conversations_returns_last_message_at_for_history_grouping(pg_session, monkeypatch):
    tenant_id = uuid4()
    created_at = datetime(2026, 4, 10, 2, 3, 42, tzinfo=UTC)
    last_message_at = datetime(2026, 4, 10, 2, 17, 14, tzinfo=UTC)
    conversation = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        title="smoke non-stream",
        title_source=chat_mod.CONVERSATION_TITLE_SOURCE_AUTO,
        document_ids=[],
        message_count=2,
        created_at=created_at,
        updated_at=datetime(2026, 4, 15, 7, 26, 4, tzinfo=UTC),
    )
    pg_session.add(conversation)
    pg_session.add(
        Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="user",
            content="hello",
            created_at=created_at,
        )
    )
    pg_session.add(
        Message(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            role="assistant",
            content="world",
            created_at=last_message_at,
        )
    )
    pg_session.commit()

    monkeypatch.setattr(chat_mod.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    payload = await chat_mod.list_conversations(
        skip=0,
        limit=20,
        tenant_id=tenant_id,
        account_id="user-1",
        db=pg_session,
    )

    item = next(entry for entry in payload["items"] if entry["id"] == conversation.id)
    assert item["updated_at"] == conversation.updated_at
    assert item["last_message_at"] == last_message_at


@pytest.mark.asyncio
async def test_chat_rejects_existing_conversation_when_bound_documents_are_gone(pg_session, monkeypatch):
    tenant_id = uuid4()
    conversation = Conversation(
        id=uuid4(),
        tenant_id=tenant_id,
        title="Stale bound chat",
        title_source=chat_mod.CONVERSATION_TITLE_SOURCE_AUTO,
        document_ids=[uuid4()],
        message_count=0,
    )
    pg_session.add(conversation)
    pg_session.commit()

    monkeypatch.setattr(chat_mod.settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)

    import app.services.tenant_quota_service as tenant_quota_service

    monkeypatch.setattr(tenant_quota_service, "enforce_tenant_qps_quota", lambda **_k: {"enabled": False}, raising=True)
    monkeypatch.setattr(chat_mod, "check_chat_assistant_token_quota", lambda *_a, **_k: {"enabled": False}, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await chat_mod.chat(
            http_request=SimpleNamespace(
                state=SimpleNamespace(request_id="req-1"),
                headers={},
                client=SimpleNamespace(host="127.0.0.1"),
            ),
            request=ChatRequest(
                conversation_id=conversation.id,
                message="Latest user question",
                stream=False,
            ),
            background_tasks=BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="user-1",
            db=pg_session,
        )

    assert exc_info.value.status_code == 409
    assert "no longer available" in str(exc_info.value.detail).lower()
