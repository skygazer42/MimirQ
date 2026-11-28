"""Table and graph metadata must survive the chat persistence JSON boundary."""

import json
from types import SimpleNamespace
from uuid import uuid4

import app.models.registry  # noqa: F401
from app.services.chat import turn_persistence


def test_persist_turn_encodes_nested_identifiers(monkeypatch):
    document_id, chunk_id = uuid4(), uuid4()
    metrics = {"tag": {"table": {"document_id": document_id}}, "matches": [{"chunk_id": chunk_id}]}
    citations = [{"document_id": document_id, "chunk_id": chunk_id, "chunk_content": "grounded result"}]
    saved = []

    def commit():
        for message in saved:
            json.dumps(message.citations)
            json.dumps(message.message_metadata)

    monkeypatch.setattr(turn_persistence, "audit_log_event", lambda *args, **kwargs: None)
    db = SimpleNamespace(add=saved.append, commit=commit)
    options = turn_persistence.ChatTurnPersistInput(
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        account_id="test-user",
        audit_action="chat.ask",
        assistant_message_id=uuid4(),
        request_id="json-contract",
        question="查验收依据",
        document_count=1,
        content="grounded result",
        citations=citations,
        metrics=metrics,
        dataset_id_used=uuid4(),
        cache_hit=False,
        ip=None,
        user_agent=None,
        enable_structured_memory=False,
        touch_conversation=False,
    )
    turn_persistence.persist_chat_turn_sync(db=db, options=options)
    assert saved[0].citations[0]["document_id"] == str(document_id)
    assert saved[0].message_metadata["tag"]["table"]["document_id"] == str(document_id)
    assert metrics["tag"]["table"]["document_id"] == document_id
    assert citations[0]["chunk_id"] == chunk_id
