from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.schemas.conversations.chat import HistoryMessage
from app.api.v1.conversations import memory


def test_history_message_requires_content_at_the_request_boundary():
    with pytest.raises(ValidationError, match="content"):
        HistoryMessage(role="user")


def test_history_message_rejects_untyped_content_blocks():
    with pytest.raises(ValidationError, match="content"):
        HistoryMessage(role="user", content=[{"type": "text"}])


@pytest.mark.parametrize("missing", ["checkpoint_id", "checkpoint_ns"])
def test_checkpoint_payload_requires_the_persisted_identity(missing):
    configurable = {"thread_id": "thread-1", "checkpoint_id": "checkpoint-1", "checkpoint_ns": ""}
    configurable.pop(missing)
    snapshot = SimpleNamespace(config={"configurable": configurable})
    with pytest.raises(KeyError, match=missing):
        memory._checkpoint_payload(snapshot, include_values=False)


def test_checkpoint_history_does_not_hide_store_failures(monkeypatch):
    from app.rag.runtime.graph import workflow

    def unavailable_history(*args, **kwargs):
        raise RuntimeError("checkpoint store unavailable")

    graph = SimpleNamespace(get_state_history=unavailable_history)
    monkeypatch.setattr(workflow, "build_rag_graph", lambda: graph)
    monkeypatch.setattr(memory, "_ensure_conversation_access", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="checkpoint store unavailable"):
        memory.list_conversation_checkpoints(uuid4(), tenant_id=uuid4(), account_id="member", db=object())
