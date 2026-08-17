"""
CSV row-aware chunking strategy.

Optimized for the lightweight CsvParser output format:
- "row 1: colA=... | colB=..."

The chunker groups whole rows into chunks and uses row-level overlap when
possible.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Row:
    start: int
    end: int
    row_no: int


_ROW_LINE_RE = re.compile(r"(?m)^\s*row\s+(?P<num>\d{1,9})\s*:\s*", flags=re.IGNORECASE)


def _iter_rows(text: str) -> list[_Row]:
    matches = list(_ROW_LINE_RE.finditer(text or ""))
    if len(matches) < 2:
        return []
    rows: list[_Row] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        try:
            row_no = int(m.group("num") or "0")
        except Exception:
            row_no = 0
        rows.append(_Row(start=start, end=end, row_no=row_no))
    return rows


def _append_fallback_documents(
    out: list[Document],
    split_docs: list[Document],
    base_meta: dict[str, Any],
) -> None:
    for split_doc in split_docs:
        local_start = split_doc.metadata.pop("start_index", None) or 0
        abs_start = int(local_start)
        abs_end = abs_start + len(split_doc.page_content)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_doc.metadata or {})
        meta["chunk_strategy"] = "csv_rows"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end
        meta["csv_rows_fallback"] = True
        out.append(Document(page_content=split_doc.page_content, metadata=meta))


def _find_chunk_end(rows: list[_Row], start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(rows):
        candidate_end = rows[end_idx].end
        candidate_len = candidate_end - rows[start_idx].start
        if end_idx == start_idx or candidate_len <= chunk_size:
            end_idx += 1
            continue
        break
    return end_idx if end_idx > start_idx else (start_idx + 1)


def _next_row_start(rows: list[_Row], start_idx: int, end_idx: int, chunk_overlap: int) -> int:
    next_start = end_idx
    if chunk_overlap > 0 and (end_idx - start_idx) > 1:
        desired = end_idx - 1
        while desired > start_idx:
            overlap_len = rows[end_idx - 1].end - rows[desired - 1].start
            if overlap_len <= chunk_overlap:
                desired -= 1
                continue
            break
        next_start = desired if desired > start_idx else (end_idx - 1)
    return end_idx if next_start <= start_idx else next_start


def _assign_chunk_indexes(chunks: list[Document]) -> None:
    for idx, chunk in enumerate(chunks):
        meta = dict(chunk.metadata or {})
        meta["chunk_index"] = idx
        chunk.metadata = meta


def looks_like_csv_rows(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    rows = _iter_rows(text)
    return len(rows) >= 3


class CsvRowsChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            rows = _iter_rows(text)
            if not rows:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                _append_fallback_documents(out, split_docs, base_meta)
                continue

            start_idx = 0
            while start_idx < len(rows):
                end_idx = _find_chunk_end(rows, start_idx, self.chunk_size)
                chunk_start = rows[start_idx].start
                chunk_end = rows[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "csv_rows"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta["csv_row_count"] = int(end_idx - start_idx)
                meta["csv_row_start"] = int(rows[start_idx].row_no)
                meta["csv_row_end"] = int(rows[end_idx - 1].row_no)
                out.append(Document(page_content=content, metadata=meta))

                start_idx = _next_row_start(rows, start_idx, end_idx, self.chunk_overlap)

        _assign_chunk_indexes(out)

        return out
