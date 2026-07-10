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

from app.rag.chunking.base import BaseChunker


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
    s = str(line or "").strip()
    if not s.startswith("##"):
        return None
    rest = s[2:].strip()
    if not rest.casefold().startswith("sheet:"):
        return None
    name = rest[len("sheet:") :].strip()
    return name or None


def _iter_sheets(text: str) -> list[_Sheet]:
    raw = text or ""
    if not raw:
        return []

    starts: list[int] = []
    names: list[str] = []
    offset = 0
    for raw_line in raw.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        name = _parse_sheet_header(raw_line.rstrip("\r\n"))
        if name is None:
            continue
        starts.append(int(line_start))
        names.append(name)

    if not starts:
        return []
    sheets: list[_Sheet] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(raw)
        name = names[idx] or ""
        if not name:
            name = f"sheet_{idx+1}"
        sheets.append(_Sheet(start=int(start), end=int(end), index=idx, name=name))
    return sheets


def looks_like_spreadsheet(text: str) -> bool:
    if not text:
        return False
    head = (text or "")[:20000]
    return any(_parse_sheet_header(ln) is not None for ln in head.splitlines())


class SpreadsheetSheetChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "。", "，", ". ", "!", "?", " ", ""],
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

            sheets = _iter_sheets(text)
            if not sheets:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "spreadsheet_sheet"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["spreadsheet_fallback"] = True
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            # Include any prefix before the first sheet as a separate chunk.
            first = sheets[0]
            if first.start > 0 and (text[: first.start] or "").strip():
                prefix = text[: first.start]
                split_docs = self._fallback_splitter.create_documents(texts=[prefix], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "spreadsheet_sheet"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["sheet_index"] = -1
                    meta["sheet_name"] = "_meta"
                    out.append(Document(page_content=sd.page_content, metadata=meta))

            for sheet in sheets:
                sheet_text = text[sheet.start : sheet.end]
                if not sheet_text.strip():
                    continue

                split_docs = self._fallback_splitter.create_documents(texts=[sheet_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = sheet.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "spreadsheet_sheet"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["sheet_index"] = int(sheet.index)
                    meta["sheet_name"] = sheet.name
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
