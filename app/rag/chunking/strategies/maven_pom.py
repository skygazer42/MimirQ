"""
Maven POM XML aware chunking strategy.

Targets pom.xml-like Maven project files and chunks by <dependency> / <plugin>
records while preserving character offsets.
"""

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Record:
    start: int
    end: int
    index: int
    kind: str
    ga: str | None


_DEPENDENCY_START_RE = re.compile(r"(?is)<dependency\b[^>]*>")
_DEPENDENCY_END_RE = re.compile(r"(?is)</dependency\s*>")
_PLUGIN_START_RE = re.compile(r"(?is)<plugin\b[^>]*>")
_PLUGIN_END_RE = re.compile(r"(?is)</plugin\s*>")
_GROUP_ID_RE = re.compile(r"(?is)<groupId\b[^>]*>(?P<body>.*?)</groupId\s*>")
_ARTIFACT_ID_RE = re.compile(r"(?is)<artifactId\b[^>]*>(?P<body>.*?)</artifactId\s*>")


def _clean_text(s: str) -> str:
    out = re.sub(r"\s+", " ", (s or "").strip())
    return out


def _extract_ga(block_text: str) -> str | None:
    head = (block_text or "")[:6000]
    gm = _GROUP_ID_RE.search(head)
    am = _ARTIFACT_ID_RE.search(head)
    if not am:
        return None
    group_id = _clean_text(gm.group("body") or "") if gm else ""
    artifact_id = _clean_text(am.group("body") or "")
    if not artifact_id:
        return None
    if group_id:
        return f"{group_id}:{artifact_id}"[:300]
    return artifact_id[:300]


def _iter_records(text: str) -> list[_Record]:
    if not text:
        return []

    records: list[_Record] = []
    for kind, start_re, end_re in (
        ("dependency", _DEPENDENCY_START_RE, _DEPENDENCY_END_RE),
        ("plugin", _PLUGIN_START_RE, _PLUGIN_END_RE),
    ):
        for sm in start_re.finditer(text):
            em = end_re.search(text, pos=sm.end())
            if not em:
                continue
            start = sm.start()
            end = em.end()
            if end < len(text) and text[end : end + 1] == "\n":
                end += 1
            blk = text[start:end]
            records.append(
                _Record(
                    start=start,
                    end=end,
                    index=0,
                    kind=kind,
                    ga=_extract_ga(blk),
                )
            )

    # Sort by start and reindex.
    records.sort(key=lambda r: (r.start, r.end))
    out: list[_Record] = []
    for r in records:
        out.append(_Record(start=r.start, end=r.end, index=len(out), kind=r.kind, ga=r.ga))
    return out


def looks_like_maven_pom(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    head = text[:20000].lower()
    if "<project" not in head:
        return False
    if "<modelversion" not in head and "<dependencies" not in head and "<dependency" not in head:
        return False
    records = _iter_records(text[:300000])
    return len(records) >= 2


def _record_window_end(records: list[_Record], *, start_idx: int, chunk_size: int) -> int:
    end_idx = start_idx
    while end_idx < len(records):
        length = records[end_idx].end - records[start_idx].start
        if end_idx != start_idx and length > chunk_size:
            break
        end_idx += 1
    return max(start_idx + 1, end_idx)


def _record_labels(
    records: list[_Record],
    *,
    start_idx: int,
    end_idx: int,
) -> tuple[list[str], list[str]]:
    kinds: list[str] = []
    artifacts: list[str] = []
    for record in records[start_idx:end_idx]:
        if record.kind not in kinds:
            kinds.append(record.kind)
        if record.ga and record.ga not in artifacts:
            artifacts.append(record.ga)
    return kinds, artifacts[:20]


def _next_record_start(
    records: list[_Record],
    *,
    start_idx: int,
    end_idx: int,
    chunk_overlap: int,
) -> int:
    next_start = end_idx
    if chunk_overlap > 0 and end_idx - start_idx > 1:
        desired = end_idx - 1
        while desired > start_idx:
            overlap_length = records[end_idx - 1].end - records[desired - 1].start
            if overlap_length > chunk_overlap:
                break
            desired -= 1
        next_start = desired if desired > start_idx else end_idx - 1
    return end_idx if next_start <= start_idx else next_start


class MavenPOMChunker(BaseChunker):
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

    def _append_fallback_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        end: int,
        base_meta: dict[str, Any],
        flag: str,
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(
            texts=[text[:end]],
            metadatas=[base_meta],
        )
        for split_doc in split_docs:
            start = int(split_doc.metadata.pop("start_index", None) or 0)
            meta: dict[str, Any] = dict(base_meta)
            meta.update(split_doc.metadata or {})
            meta.update(
                {
                    "chunk_strategy": "maven_pom",
                    "start_char": start,
                    "end_char": start + len(split_doc.page_content),
                    flag: True,
                }
            )
            meta.setdefault("doc_type_kwd", "maven")
            out.append(Document(page_content=split_doc.page_content, metadata=meta))

    @staticmethod
    def _record_metadata(
        *,
        base_meta: dict[str, Any],
        records: list[_Record],
        start_idx: int,
        end_idx: int,
    ) -> dict[str, Any]:
        first = records[start_idx]
        last = records[end_idx - 1]
        kinds, artifacts = _record_labels(records, start_idx=start_idx, end_idx=end_idx)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(
            {
                "chunk_strategy": "maven_pom",
                "start_char": first.start,
                "end_char": last.end,
                "maven_record_count": int(end_idx - start_idx),
                "maven_first_index": int(first.index),
                "maven_last_index": int(last.index),
            }
        )
        meta.setdefault("doc_type_kwd", "maven")
        if kinds:
            meta["maven_kinds"] = kinds
        if artifacts:
            meta["maven_artifacts"] = artifacts
        return meta

    def _append_record_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        records: list[_Record],
        base_meta: dict[str, Any],
    ) -> None:
        start_idx = 0
        while start_idx < len(records):
            end_idx = _record_window_end(
                records,
                start_idx=start_idx,
                chunk_size=self.chunk_size,
            )
            meta = self._record_metadata(
                base_meta=base_meta,
                records=records,
                start_idx=start_idx,
                end_idx=end_idx,
            )
            out.append(
                Document(
                    page_content=text[meta["start_char"] : meta["end_char"]],
                    metadata=meta,
                )
            )
            start_idx = _next_record_start(
                records,
                start_idx=start_idx,
                end_idx=end_idx,
                chunk_overlap=self.chunk_overlap,
            )

    def _split_document(self, doc: Document, out: list[Document]) -> None:
        text = doc.page_content or ""
        if not text.strip():
            return
        base_meta = dict(doc.metadata or {})
        records = _iter_records(text)
        if not records:
            self._append_fallback_chunks(
                out,
                text=text,
                end=len(text),
                base_meta=base_meta,
                flag="maven_pom_fallback",
            )
            return
        if records[0].start > 0 and text[: records[0].start].strip():
            self._append_fallback_chunks(
                out,
                text=text,
                end=records[0].start,
                base_meta=base_meta,
                flag="maven_pom_preamble",
            )
        self._append_record_chunks(
            out,
            text=text,
            records=records,
            base_meta=base_meta,
        )

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []
        for doc in documents:
            self._split_document(doc, out)
        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta
        return out
