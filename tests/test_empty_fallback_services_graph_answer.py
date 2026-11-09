from app.services.chat_stream_graph import _consume_graph_value_chunk


def test_graph_snapshot_without_an_answer_does_not_consume_the_answer_update():
    parts = []
    events, citations_sent, answer_sent, _ = _consume_graph_value_chunk(
        chunk={"answer": None}, citations_sent=False, answer_sent=False, response_parts=parts
    )
    assert events == []
    assert answer_sent is False

    events, _, answer_sent, _ = _consume_graph_value_chunk(
        chunk={"answer": "Ready answer"},
        citations_sent=citations_sent,
        answer_sent=answer_sent,
        response_parts=parts,
    )
    assert answer_sent is True
    assert parts == ["Ready answer"]
    assert events == [{"type": "token", "data": {"content": "Ready answer"}}]
