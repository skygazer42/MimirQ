"""
Spreadsheet (XLSX/CSV-to-markdown) sheet-aware chunking strategy.

Optimized for the lightweight ExcelParser output format:
- "## Sheet: <name>" sections

The chunker splits by sheets first, then applies a fallback splitter inside
each sheet while preserving character offsets.
"""

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.utils.source_lines import apply_splitter_span


@dataclass(frozen=True)
class _Sheet:
    start: int
    end: int
    index: int
    name: str


def _parse_sheet_header(line: str) -> str | None:
    """
    Parse a sheet header line like:
      ## Sheet: Name

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = line.strip()
    if not s.startswith("##"):
        return None
    rest = s[2:].strip()
    if not rest.casefold().startswith("sheet:"):
        return None
    name = rest[len("sheet:") :].strip()
    return name or None


def _iter_sheets(text: str) -> list[_Sheet]:
    headers: list[tuple[int, str]] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        name = _parse_sheet_header(raw_line.rstrip("\r\n"))
        if name is None:
            continue
        headers.append((line_start, name))

    sheets: list[_Sheet] = []
    for idx, (start, name) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(text)
        sheets.append(_Sheet(start=start, end=end, index=idx, name=name))
    return sheets


def looks_like_spreadsheet(text: str) -> bool:
    if not text:
        return False
    head = (text)[:20000]
    return any(_parse_sheet_header(ln) is not None for ln in head.splitlines())


class SpreadsheetSheetChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "，", ". ", "!", "?", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def _append_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        base_meta: dict[str, Any],
        offset: int,
        extra_meta: dict[str, Any],
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
        for sd in split_docs:
            local_start = sd.metadata.pop("start_index", None)
            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd.metadata)
            meta["chunk_strategy"] = "spreadsheet_sheet"
            apply_splitter_span(meta, start_index=local_start, content=sd.page_content, base_offset=offset)
            meta.update(extra_meta)
            out.append(Document(page_content=sd.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content
            base_meta = dict(doc.metadata)
            if not text.strip():
                continue

            sheets = _iter_sheets(text)
            if not sheets:
                self._append_chunks(
                    out,
                    text=text,
                    base_meta=base_meta,
                    offset=0,
                    extra_meta={"spreadsheet_fallback": True},
                )
                continue

            # Include any prefix before the first sheet as a separate chunk.
            first = sheets[0]
            if first.start > 0 and (text[: first.start]).strip():
                prefix = text[: first.start]
                self._append_chunks(
                    out,
                    text=prefix,
                    base_meta=base_meta,
                    offset=0,
                    extra_meta={"sheet_index": -1, "sheet_name": "_meta"},
                )

            for sheet in sheets:
                sheet_text = text[sheet.start : sheet.end]
                self._append_chunks(
                    out,
                    text=sheet_text,
                    base_meta=base_meta,
                    offset=sheet.start,
                    extra_meta={"sheet_index": sheet.index, "sheet_name": sheet.name},
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata)
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
