"""
JUnit XML report aware chunking strategy.

Targets JUnit-style XML reports with repeated <testcase> elements and splits by
testcase blocks while preserving offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


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


def _extract_attr(tag_text: str, key: str) -> str | None:
    if not tag_text:
        return None
    for m in _ATTR_RE.finditer(tag_text[:800]):
        if (m.group("key") or "").strip() == key:
            val = (m.group("val") or "").strip()
            return val[:200] or None
    return None


def _build_testcase_blocks(text: str) -> list[_CaseBlock]:
    if not text:
        return []
    blocks: list[_CaseBlock] = []
    for m in _TESTCASE_ANY_RE.finditer(text):
        start = m.start()
        tag = (m.group(0) or "")
        if tag.rstrip().endswith("/>"):
            end = m.end()
        else:
            em = _TESTCASE_END_RE.search(text, pos=m.end())
            if not em:
                continue
            end = em.end()
        name = _extract_attr(tag, "name")
        classname = _extract_attr(tag, "classname")
        if end < len(text) and text[end : end + 1] == "\n":
            end += 1
        blocks.append(_CaseBlock(start=start, end=end, index=len(blocks), name=name, classname=classname))
    return blocks


def looks_like_junit_xml(text: str) -> bool:
    if not text or len(text) < 80:
        return False
    head = text[:200000]
    if not _TESTSUITE_HINT_RE.search(head):
        return False
    if len(_TESTCASE_ANY_RE.findall(head)) < 2:
        return False
    blocks = _build_testcase_blocks(text)
    return len(blocks) >= 2


class JUnitXMLChunker(BaseChunker):
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

            blocks = _build_testcase_blocks(text)
            if not blocks:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "junit_xml"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["junit_xml_fallback"] = True
                    meta.setdefault("doc_type_kwd", "junit")
                    out.append(Document(page_content=sd.page_content, metadata=meta))
                continue

            first = blocks[0]
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
                        meta["chunk_strategy"] = "junit_xml"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["junit_xml_preamble"] = True
                        meta.setdefault("doc_type_kwd", "junit")
                        out.append(Document(page_content=sd.page_content, metadata=meta))

            for blk in blocks:
                blk_text = text[blk.start : blk.end]
                if not blk_text.strip():
                    continue
                split_docs = self._fallback_splitter.create_documents(texts=[blk_text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = blk.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)

                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "junit_xml"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "junit")
                    meta["junit_case_index"] = int(blk.index)
                    meta["junit_case_count"] = int(len(blocks))
                    if blk.name:
                        meta["junit_case"] = blk.name
                    if blk.classname:
                        meta["junit_classname"] = blk.classname
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
