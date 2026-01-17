"""
Spreadsheet (XLSX/CSV-to-markdown) sheet-aware chunking strategy.

Optimized for the lightweight ExcelParser output format:
- "## Sheet: <name>" sections

The chunker splits by sheets first, then applies a fallback splitter inside
each sheet while preserving character offsets.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Sheet:
    start: int
    end: int
    index: int
    name: str


_SHEET_RE = re.compile(r"(?m)^##\s*Sheet:\s*(?P<name>.+?)\s*$")


def _iter_sheets(text: str) -> List[_Sheet]:
    matches = list(_SHEET_RE.finditer(text or ""))
    if not matches:
        return []
    sheets: List[_Sheet] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        name = (m.group("name") or "").strip()
        if not name:
            name = f"sheet_{idx+1}"
        sheets.append(_Sheet(start=start, end=end, index=idx, name=name))
    return sheets


def looks_like_spreadsheet(text: str) -> bool:
    if not text:
        return False
    return bool(_SHEET_RE.search(text))


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

    def split_documents(self, documents: List[Document]) -> List[Document]:
        out: List[Document] = []

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
