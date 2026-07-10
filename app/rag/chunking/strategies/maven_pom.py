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
                    meta["chunk_strategy"] = "maven_pom"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["maven_pom_fallback"] = True
                    meta.setdefault("doc_type_kwd", "maven")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            first = records[0]
            if first.start > 0:
                pre = text[: first.start]
                if pre.strip():
                    split_docs = self._fallback_splitter.create_documents(texts=[pre], metadatas=[base_meta])
                    for sd in split_docs:
                        local_start = sd.metadata.pop("start_index", None) or 0
                        abs_start = int(local_start)
                        abs_end = abs_start + len(sd.page_content)
                        meta: dict[str, Any] = dict(base_meta)
                        meta.update(sd.metadata or {})
                        meta["chunk_strategy"] = "maven_pom"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["maven_pom_preamble"] = True
                        meta.setdefault("doc_type_kwd", "maven")
                        out.append(Document(page_content=sd.page_content, metadata=meta))

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

                gas: list[str] = []
                kinds: list[str] = []
                for r in records[start_idx:end_idx]:
                    if r.kind not in kinds:
                        kinds.append(r.kind)
                    if r.ga and r.ga not in gas:
                        gas.append(r.ga)
                gas = gas[:20]

                meta: dict[str, Any] = dict(base_meta)
                meta["chunk_strategy"] = "maven_pom"
                meta["start_char"] = chunk_start
                meta["end_char"] = chunk_end
                meta.setdefault("doc_type_kwd", "maven")
                meta["maven_record_count"] = int(end_idx - start_idx)
                meta["maven_first_index"] = int(records[start_idx].index)
                meta["maven_last_index"] = int(records[end_idx - 1].index)
                if kinds:
                    meta["maven_kinds"] = kinds
                if gas:
                    meta["maven_artifacts"] = gas
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
