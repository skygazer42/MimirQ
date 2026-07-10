"""
JSONL / NDJSON record-aware chunking strategy.

Targets newline-delimited JSON where each non-empty line is a JSON object/array.
The chunker groups whole records together while preserving character offsets.
"""


import json
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Line:
    start: int
    end: int
    plain: str


@dataclass(frozen=True)
class _Record:
    start: int
    end: int
    index: int
    keys: list[str]


_COMMENT_RE = re.compile(r"^\s*(#|//)")


def _iter_lines(text: str) -> list[_Line]:
    out: list[_Line] = []
    offset = 0
    for raw in (text or "").splitlines(keepends=True):
        start = offset
        end = start + len(raw)
        offset = end
        out.append(_Line(start=start, end=end, plain=raw.rstrip("\r\n")))
    if not out and text:
        out.append(_Line(start=0, end=len(text), plain=text))
    return out


def _try_parse_json_line(line: str) -> tuple[Any, list[str]] | None:
    s = (line or "").strip()
    if not s:
        return None
    if _COMMENT_RE.match(s):
        return None
    if s[0] not in "{[":
        return None
    try:
        obj = json.loads(s)
    except ValueError:
        return None
    keys: list[str] = []
    if isinstance(obj, dict):
        for k in obj:
            if isinstance(k, str):
                keys.append(k)
    return obj, keys


def _iter_records(text: str) -> list[_Record]:
    records: list[_Record] = []
    for ln in _iter_lines(text):
        parsed = _try_parse_json_line(ln.plain)
        if not parsed:
            continue
        _, keys = parsed
        records.append(_Record(start=ln.start, end=ln.end, index=len(records), keys=keys))
    return records


def looks_like_jsonl_records(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    lines = [ln for ln in (text or "").splitlines() if ln.strip() and not _COMMENT_RE.match(ln)]
    if len(lines) < 3:
        return False
    sample = lines[:60]
    parseable = 0
    for ln in sample:
        if _try_parse_json_line(ln) is not None:
            parseable += 1
    return parseable >= 3 and (parseable / max(1, len(sample))) >= 0.4


class JsonlRecordsChunker(BaseChunker):
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

            records = _iter_records(text)
            if not records:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "jsonl_records"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["jsonl_fallback"] = True
                    meta.setdefault("doc_type_kwd", "jsonl")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            start_idx = 0
            while start_idx < len(records):
                end_idx = start_idx
                while end_idx < len(records):
                    cand_start = records[start_idx].start
                    cand_end = records[end_idx].end
                    cand_len = cand_end - cand_start
                    if end_idx == start_idx or cand_len <= self.chunk_size:
                        end_idx += 1
                        continue
                    break
                if end_idx == start_idx:
                    end_idx = start_idx + 1

                chunk_start = records[start_idx].start
                chunk_end = records[end_idx - 1].end
                content = text[chunk_start:chunk_end]

                keys: list[str] = []
                for r in records[start_idx:end_idx]:
                    for k in r.keys:
                        if k not in keys:
                            keys.append(k)
                keys = keys[:25]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "jsonl_records"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta.setdefault("doc_type_kwd", "jsonl")
                meta["jsonl_record_count"] = int(end_idx - start_idx)
                meta["jsonl_first_index"] = int(records[start_idx].index)
                meta["jsonl_last_index"] = int(records[end_idx - 1].index)
                if keys:
                    meta["jsonl_keys"] = keys
                out.append(Document(page_content=content, metadata=meta))

                next_start = end_idx
                if self.chunk_overlap > 0 and (end_idx - start_idx) > 1:
                    desired = end_idx - 1
                    while desired > start_idx:
                        overlap_len = records[end_idx - 1].end - records[desired - 1].start
                        if overlap_len <= self.chunk_overlap:
                            desired -= 1
                            continue
                        break
                    next_start = desired if desired > start_idx else (end_idx - 1)

                if next_start <= start_idx:
                    next_start = end_idx
                start_idx = next_start

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
