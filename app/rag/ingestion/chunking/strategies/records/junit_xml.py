"""
JUnit XML report aware chunking strategy.

Targets JUnit-style XML reports with repeated <testcase> elements and splits by
testcase blocks while preserving offsets.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.ingestion.chunking.base import BaseChunker
from app.rag.ingestion.chunking.utils.source_lines import apply_splitter_span


@dataclass(frozen=True)
class _CaseBlock:
    start: int
    end: int
    index: int
    name: str | None
    classname: str | None


_TESTCASE_ANY_RE = re.compile(r"(?is)<testcase\b[^>]*?/\s*>|<testcase\b[^>]*>")
_TESTCASE_END_RE = re.compile(r"(?is)</testcase\s*>")
_TESTSUITE_HINT_RE = re.compile(r"(?is)<testsuites\b|<testsuite\b")
_ATTR_RE = re.compile(r"(?P<key>[A-Za-z_:][A-Za-z0-9_.:-]*)\s*=\s*(?P<q>['\"])(?P<val>.*?)(?P=q)")


def _testcase_attributes(tag_text: str) -> tuple[str | None, str | None]:
    values: dict[str, str | None] = {}
    for match in _ATTR_RE.finditer(tag_text[:800]):
        key = match.group("key")
        if key in {"name", "classname"} and key not in values:
            values[key] = match.group("val").strip()[:200] or None
            if len(values) == 2:
                break
    return values.get("name"), values.get("classname")


def _iter_testcase_blocks(text: str) -> Iterator[_CaseBlock]:
    index = 0
    for m in _TESTCASE_ANY_RE.finditer(text):
        start = m.start()
        tag = m.group(0)
        if tag.rstrip().endswith("/>"):
            end = m.end()
        else:
            em = _TESTCASE_END_RE.search(text, pos=m.end())
            if not em:
                continue
            end = em.end()
        name, classname = _testcase_attributes(tag)
        if end < len(text) and text[end : end + 1] == "\n":
            end += 1
        yield _CaseBlock(start=start, end=end, index=index, name=name, classname=classname)
        index += 1


def _append_split_documents(
    out: list[Document],
    split_docs: list[Document],
    base_meta: dict[str, Any],
    *,
    offset_base: int = 0,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    for split_doc in split_docs:
        local_start = split_doc.metadata.pop("start_index", None)
        meta: dict[str, Any] = dict(base_meta)
        meta.update(split_doc.metadata)
        meta["chunk_strategy"] = "junit_xml"
        apply_splitter_span(meta, start_index=local_start, content=split_doc.page_content, base_offset=offset_base)
        meta.setdefault("doc_type_kwd", "junit")
        if extra_meta:
            meta.update(extra_meta)
        meta["chunk_index"] = len(out)
        out.append(Document(page_content=split_doc.page_content, metadata=meta))


def _case_block_meta(block: _CaseBlock, block_count: int) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "junit_case_index": block.index,
        "junit_case_count": block_count,
    }
    if block.name:
        meta["junit_case"] = block.name
    if block.classname:
        meta["junit_classname"] = block.classname
    return meta


def looks_like_junit_xml(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    head = text[:200000]
    if not _TESTSUITE_HINT_RE.search(head):
        return False
    if len(_TESTCASE_ANY_RE.findall(head)) < 2:
        return False
    return any(block.index == 1 for block in _iter_testcase_blocks(text))


class JUnitXMLChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int) -> None:
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
            text = doc.page_content
            base_meta = dict(doc.metadata)
            if not text.strip():
                continue

            blocks = list(_iter_testcase_blocks(text))
            if not blocks:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                _append_split_documents(out, split_docs, base_meta, extra_meta={"junit_xml_fallback": True})
                continue

            first = blocks[0]
            if first.start > 0:
                pre = text[: first.start]
                if pre.strip():
                    split_docs = self._fallback_splitter.create_documents(texts=[pre], metadatas=[base_meta])
                    _append_split_documents(out, split_docs, base_meta, extra_meta={"junit_xml_preamble": True})

            covered_end = blocks[0].start
            for blk in blocks:
                gap = text[covered_end : blk.start]
                if blk.start > covered_end and gap.strip():
                    split_docs = self._fallback_splitter.create_documents(texts=[gap], metadatas=[base_meta])
                    _append_split_documents(
                        out,
                        split_docs,
                        base_meta,
                        offset_base=covered_end,
                        extra_meta={"junit_xml_unstructured": True},
                    )
                blk_text = text[blk.start : blk.end]
                if not blk_text.strip():
                    continue
                split_docs = self._fallback_splitter.create_documents(texts=[blk_text], metadatas=[base_meta])
                _append_split_documents(
                    out,
                    split_docs,
                    base_meta,
                    offset_base=blk.start,
                    extra_meta=_case_block_meta(blk, len(blocks)),
                )
                covered_end = max(covered_end, blk.end)
            tail = text[covered_end:]
            if tail.strip():
                split_docs = self._fallback_splitter.create_documents(texts=[tail], metadatas=[base_meta])
                _append_split_documents(
                    out,
                    split_docs,
                    base_meta,
                    offset_base=covered_end,
                    extra_meta={"junit_xml_unstructured": True},
                )

        return out
