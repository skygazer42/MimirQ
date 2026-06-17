from uuid import uuid4

from app.services.ragas_conversation_readiness import conversation_readiness_items


def test_conversation_readiness_counts_citation_backed_assistant_turns():
    ready_id = uuid4()
    missing_id = uuid4()

    items = conversation_readiness_items(
        [ready_id, missing_id],
        [
            (ready_id, [{"document_id": "doc-1"}, {"document_id": "doc-2"}]),
            (ready_id, []),
            (missing_id, []),
        ],
    )

    by_id = {item.conversation_id: item for item in items}

    assert by_id[ready_id].assistant_turns == 2
    assert by_id[ready_id].evaluable_turns == 1
    assert by_id[ready_id].citations_count == 2
    assert by_id[ready_id].is_evaluable is True

    assert by_id[missing_id].assistant_turns == 1
    assert by_id[missing_id].evaluable_turns == 0
    assert by_id[missing_id].citations_count == 0
    assert by_id[missing_id].is_evaluable is False
