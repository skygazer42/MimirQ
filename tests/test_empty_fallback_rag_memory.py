from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from app.rag.checkpointer.time_travel import TimeTravel
from app.rag.memory.short_term import _message_to_tokens, trim_messages


def test_history_message_conversion_requires_the_content_key():
    with pytest.raises(KeyError, match="content"):
        trim_messages([{"role": "human"}], max_tokens=100)


def test_text_content_blocks_require_their_text_key():
    with pytest.raises(KeyError, match="text"):
        _message_to_tokens(HumanMessage(content=[{"type": "text"}]))


def test_checkpoint_history_requires_the_persisted_checkpoint_id():
    state = SimpleNamespace(
        config={"configurable": {"thread_id": "thread-1"}},
        parent_config=None,
        metadata={},
        values={},
        next=(),
    )
    graph = SimpleNamespace(checkpointer=object(), get_state_history=lambda *args, **kwargs: [state])
    with pytest.raises(KeyError, match="checkpoint_id"):
        TimeTravel(graph).get_history("thread-1")


def test_checkpoint_history_does_not_hide_store_failures():
    def unavailable_history(*args, **kwargs):
        raise RuntimeError("checkpoint store unavailable")

    graph = SimpleNamespace(checkpointer=object(), get_state_history=unavailable_history)
    with pytest.raises(RuntimeError, match="checkpoint store unavailable"):
        TimeTravel(graph).get_history("thread-1")


def test_checkpoint_fork_requires_the_new_checkpoint_identity():
    graph = SimpleNamespace(
        checkpointer=object(), update_state=lambda *args, **kwargs: {"configurable": {"thread_id": "thread-1"}}
    )
    with pytest.raises(KeyError, match="checkpoint_id"):
        TimeTravel(graph).fork("thread-1", "checkpoint-1", {}, continue_execution=False)
