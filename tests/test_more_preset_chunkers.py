from langchain_core.documents import Document

from app.rag.chunking.strategies.api_reference import APIReferenceChunker
from app.rag.chunking.strategies.changelog import ChangelogChunker
from app.rag.chunking.strategies.diff_patch import DiffPatchChunker
from app.rag.chunking.strategies.kv_config import KVConfigChunker
from app.rag.chunking.strategies.log_events import LogEventsChunker
from app.rag.chunking.strategies.meeting_minutes import MeetingMinutesChunker
from app.rag.chunking.strategies.qa_markdown import QAMarkdownChunker
from app.rag.chunking.strategies.subtitles import SubtitlesChunker
from app.rag.chunking.strategies.timeline_events import TimelineEventsChunker


def test_changelog_chunker_preserves_offsets_and_release_metadata():
    text = (
        "# Changelog\n\n"
        "## [1.0.0] - 2024-01-01\n"
        + ("Added feature. " * 20).strip()
        + "\n\n"
        "## [0.9.0] - 2023-12-01\n"
        + ("Fixed bug. " * 20).strip()
        + "\n"
    )
    chunker = ChangelogChunker(chunk_size=220, chunk_overlap=40)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "changelog"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    assert any((c.metadata or {}).get("release_version") == "1.0.0" for c in chunks)
    assert any((c.metadata or {}).get("release_date") for c in chunks)


def test_log_events_chunker_preserves_offsets_and_log_levels():
    text = (
        "2024-01-01 10:00:00,123 INFO service: started\n"
        "2024-01-01 10:00:01,456 WARN service: warming up\n"
        "2024-01-01 10:00:02,789 ERROR service: failed\n"
        "Traceback (most recent call last):\n"
        "  File \"x.py\", line 1, in <module>\n"
        "    boom()\n"
        "2024-01-01 10:00:03,000 INFO service: recovered\n"
    )
    chunker = LogEventsChunker(chunk_size=220, chunk_overlap=60)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "log_events"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert int(meta.get("log_entry_count") or 0) >= 1

    levels = []
    for c in chunks:
        levels.extend((c.metadata or {}).get("log_levels") or [])
    assert "INFO" in levels or "ERROR" in levels


def test_subtitles_chunker_preserves_offsets_and_timecodes():
    text = (
        "1\n"
        "00:00:01,000 --> 00:00:02,000\n"
        "Hello.\n\n"
        "2\n"
        "00:00:03,000 --> 00:00:04,000\n"
        "World.\n\n"
        "3\n"
        "00:00:05,000 --> 00:00:06,000\n"
        "Again.\n\n"
        "4\n"
        "00:00:07,000 --> 00:00:08,000\n"
        "Done.\n"
    )
    chunker = SubtitlesChunker(chunk_size=160, chunk_overlap=40)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "subtitles"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    assert any((c.metadata or {}).get("first_timecode") for c in chunks)
    assert any(int((c.metadata or {}).get("cue_count") or 0) >= 1 for c in chunks)


def test_api_reference_chunker_preserves_offsets_and_endpoint_metadata():
    text = (
        "# API\n\n"
        "GET /health\n"
        + ("Returns ok. " * 15).strip()
        + "\n\n"
        "POST /api/v1/items\n"
        + ("Creates item. " * 15).strip()
        + "\n\n"
        "DELETE /api/v1/items/{id}\n"
        + ("Deletes item. " * 15).strip()
        + "\n"
    )
    chunker = APIReferenceChunker(chunk_size=220, chunk_overlap=40)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "api_reference"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    assert any((c.metadata or {}).get("http_method") == "GET" for c in chunks)
    assert any((c.metadata or {}).get("api_path") == "/health" for c in chunks)


def test_diff_patch_chunker_preserves_offsets_and_diff_metadata():
    text = (
        "diff --git a/foo.txt b/foo.txt\n"
        "index 1111111..2222222 100644\n"
        "--- a/foo.txt\n"
        "+++ b/foo.txt\n"
        "@@ -1,2 +1,2 @@\n"
        "-old\n"
        "+new\n"
        "@@ -4,1 +4,1 @@\n"
        "-old2\n"
        "+new2\n"
        "diff --git a/bar.txt b/bar.txt\n"
        "index 3333333..4444444 100644\n"
        "--- a/bar.txt\n"
        "+++ b/bar.txt\n"
        "@@ -1,1 +1,1 @@\n"
        "-x\n"
        "+y\n"
    )
    chunker = DiffPatchChunker(chunk_size=240, chunk_overlap=60)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "diff_patch"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert "diff_path_a" in meta
        assert "diff_path_b" in meta

    assert any((c.metadata or {}).get("diff_hunk_count") for c in chunks)


def test_kv_config_chunker_preserves_offsets_and_keys():
    text = (
        "# Example config\n"
        "DATABASE_URL=postgresql://localhost:5432/db\n"
        "API_KEY=secret\n"
        "export DEBUG=true\n"
        "TIMEOUT_SEC=30\n"
        "RETRY_MAX=2\n\n"
        "[extra]\n"
        "foo=bar\n"
        "baz=qux\n"
    )
    chunker = KVConfigChunker(chunk_size=200, chunk_overlap=50)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "kv_config"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    keys = []
    for c in chunks:
        keys.extend((c.metadata or {}).get("kv_keys") or [])
    assert "DATABASE_URL" in keys
    assert "API_KEY" in keys


def test_qa_markdown_chunker_preserves_offsets_and_pairs():
    text = (
        "- **Q:** What is RAG?\n"
        "- **A:** Retrieval-Augmented Generation.\n\n"
        "- **Q:** Why chunk?\n"
        "- **A:** Better retrieval.\n"
    )
    chunker = QAMarkdownChunker(chunk_size=160, chunk_overlap=40)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "qa_markdown"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert int(meta.get("qa_pair_count") or 0) >= 1


def test_meeting_minutes_chunker_preserves_offsets_and_section_metadata():
    text = (
        "Meeting Notes\n\n"
        "Agenda:\n"
        "- Review progress\n"
        "- Discuss risks\n\n"
        "Action Items:\n"
        "- Alice: update docs\n"
        "- Bob: run tests\n\n"
        "Decisions:\n"
        "- Ship on Friday\n"
    )
    chunker = MeetingMinutesChunker(chunk_size=200, chunk_overlap=40)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "meeting_minutes"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    assert any((c.metadata or {}).get("minutes_section") for c in chunks)


def test_timeline_events_chunker_preserves_offsets_and_event_metadata():
    text = (
        "2024-01-01 - Kickoff\n"
        "Notes...\n"
        "2024-01-02 - Planning\n"
        "More...\n"
        "2024-01-03 - Execution\n"
        "More...\n"
        "2024-01-04 - Wrap up\n"
        "Done.\n"
    )
    chunker = TimelineEventsChunker(chunk_size=220, chunk_overlap=60)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "timeline_events"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert int(meta.get("event_count") or 0) >= 1

    assert any((c.metadata or {}).get("first_event") for c in chunks)

