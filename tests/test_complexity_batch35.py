from langchain_core.documents import Document

from app.rag.ingestion.chunking.strategies.records.log_events import LogEventsChunker, _iter_entries


def test_log_event_chunker_preserves_entry_overlap_levels_and_offsets() -> None:
    text = (
        "preamble\n"
        "2026-01-01 10:00:00 INFO app: first\n"
        "  detail\n"
        "2026-01-01 10:00:01 ERROR app: second\n"
        "2026-01-01 10:00:02 WARN app: third\n"
        "2026-01-01 10:00:03 INFO app: fourth\n"
    )
    assert [(entry.start, entry.end, entry.ts, entry.level) for entry in _iter_entries(text)] == [
        (9, 54, "2026-01-01 10:00:00", "INFO"),
        (54, 92, "2026-01-01 10:00:01", "ERROR"),
        (92, 128, "2026-01-01 10:00:02", "WARN"),
        (128, 165, "2026-01-01 10:00:03", "INFO"),
    ]

    chunks = LogEventsChunker(95, 20).split_documents([Document(page_content=text, metadata={"source": "fixture"})])
    assert chunks[0].page_content == "preamble"
    assert chunks[0].metadata["log_fallback"] is True
    assert [
        (
            chunk.metadata["start_char"],
            chunk.metadata["end_char"],
            chunk.metadata["log_entry_count"],
            chunk.metadata["log_levels"],
            chunk.metadata["first_timestamp"],
            chunk.metadata["last_timestamp"],
            chunk.metadata["chunk_index"],
        )
        for chunk in chunks[1:]
    ] == [
        (9, 92, 2, ["INFO", "ERROR"], "2026-01-01 10:00:00", "2026-01-01 10:00:01", 1),
        (54, 128, 2, ["ERROR", "WARN"], "2026-01-01 10:00:01", "2026-01-01 10:00:02", 2),
        (92, 165, 2, ["WARN", "INFO"], "2026-01-01 10:00:02", "2026-01-01 10:00:03", 3),
    ]
