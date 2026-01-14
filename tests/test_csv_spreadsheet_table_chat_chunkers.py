from langchain_core.documents import Document

from app.rag.chunking.strategies.chat_history import ChatHistoryChunker
from app.rag.chunking.strategies.csv_rows import CsvRowsChunker
from app.rag.chunking.strategies.markdown_table import MarkdownTableChunker
from app.rag.chunking.strategies.spreadsheet_sheet import SpreadsheetSheetChunker


def test_csv_rows_chunker_preserves_offsets_and_row_metadata():
    text = (
        "CSV: demo.csv\n"
        "Delimiter: ','\n"
        "Columns: name, age, note\n\n"
        "row 1: name=Alice | age=30 | note=" + ("a" * 40) + "\n"
        "row 2: name=Bob | age=31 | note=" + ("b" * 40) + "\n"
        "row 3: name=Carol | age=29 | note=" + ("c" * 40) + "\n"
        "row 4: name=Dave | age=40 | note=" + ("d" * 40) + "\n"
    )
    chunker = CsvRowsChunker(chunk_size=160, chunk_overlap=60)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "csv"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "csv_rows"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert int(meta.get("csv_row_count") or 0) >= 1

    assert any(int((c.metadata or {}).get("csv_row_start") or 0) >= 1 for c in chunks)


def test_spreadsheet_sheet_chunker_preserves_offsets_and_sheet_metadata():
    text = (
        "Excel: demo.xlsx\n"
        "Sheets: Sheet1, Sheet2\n\n"
        "## Sheet: Sheet1\n\n"
        "| A | B |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n\n"
        "## Sheet: Sheet2\n\n"
        "| X | Y |\n"
        "| --- | --- |\n"
        "| a | b |\n"
    )
    chunker = SpreadsheetSheetChunker(chunk_size=140, chunk_overlap=20)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "xlsx"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "spreadsheet_sheet"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert "sheet_name" in meta

    assert any((c.metadata or {}).get("sheet_name") == "Sheet1" for c in chunks)
    assert any((c.metadata or {}).get("sheet_name") == "Sheet2" for c in chunks)


def test_markdown_table_chunker_preserves_offsets_and_table_metadata():
    text = (
        "Here is the table:\n\n"
        "| Name | Score |\n"
        "| --- | --- |\n"
        "| Alice | 90 |\n"
        "| Bob | 85 |\n"
        "| Carol | 95 |\n\n"
        "End.\n"
    )
    chunker = MarkdownTableChunker(chunk_size=90, chunk_overlap=30)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "md"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "markdown_table"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content

    table_chunks = [c for c in chunks if (c.metadata or {}).get("doc_type_kwd") == "table"]
    assert table_chunks
    assert any((c.metadata or {}).get("table_header") for c in table_chunks)


def test_chat_history_chunker_preserves_offsets_and_participants_metadata():
    text = (
        "[2024-01-01 10:00] Alice: " + ("hello " * 10).strip() + "\n"
        "[2024-01-01 10:01] Bob: " + ("hi " * 12).strip() + "\n"
        "[2024-01-01 10:02] Alice: " + ("update " * 10).strip() + "\n"
        "[2024-01-01 10:03] Bob: " + ("thanks " * 10).strip() + "\n"
    )
    chunker = ChatHistoryChunker(chunk_size=200, chunk_overlap=60)
    chunks = chunker.split_documents([Document(page_content=text, metadata={"file_type": "txt"})])

    assert chunks
    for idx, chunk in enumerate(chunks):
        meta = chunk.metadata
        assert meta.get("chunk_strategy") == "chat_history"
        assert meta.get("chunk_index") == idx
        start = int(meta["start_char"])
        end = int(meta["end_char"])
        assert text[start:end] == chunk.page_content
        assert int(meta.get("message_count") or 0) >= 1

    participants = []
    for c in chunks:
        participants.extend((c.metadata or {}).get("participants") or [])
    assert "Alice" in participants
    assert "Bob" in participants

