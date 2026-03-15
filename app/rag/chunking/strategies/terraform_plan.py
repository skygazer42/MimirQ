"""
Terraform plan output aware chunking strategy.

Targets `terraform plan` / `terraform apply` text output and splits by resource
change blocks (lines like "# aws_instance.example will be created") while
preserving character offsets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _ChangeBlock:
    start: int
    end: int
    index: int
    address: str
    action: str


_CHANGE_RE = re.compile(r"(?m)^\s*#\s+(?P<addr>.+?)\s+will\s+be\s+(?P<action>.+?)\s*$")
_PLAN_HINT_RE = re.compile(r"(?i)terraform\s+will\s+perform\s+the\s+following\s+actions|^\s*Plan:\s*\d+", re.MULTILINE)


def _build_change_blocks(text: str) -> list[_ChangeBlock]:
    matches = list(_CHANGE_RE.finditer(text or ""))
    if not matches:
        return []
    blocks: list[_ChangeBlock] = []
    for idx, m in enumerate(matches):
        start = m.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        addr = (m.group("addr") or "").strip()[:300]
        action = (m.group("action") or "").strip()[:80]
        blocks.append(_ChangeBlock(start=start, end=end, index=int(idx), address=addr, action=action))
    return blocks


def looks_like_terraform_plan(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    head = (text or "")[:200000]
    if not _PLAN_HINT_RE.search(head):
        return False
    blocks = _build_change_blocks(text)
    return len(blocks) >= 1


class TerraformPlanChunker(BaseChunker):
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

            blocks = _build_change_blocks(text)
            if not blocks:
                split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
                for sd in split_docs:
                    local_start = sd.metadata.pop("start_index", None) or 0
                    abs_start = int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    meta: dict[str, Any] = dict(base_meta)
                    meta.update(sd.metadata or {})
                    meta["chunk_strategy"] = "terraform_plan"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta["terraform_plan_fallback"] = True
                    meta.setdefault("doc_type_kwd", "terraform")
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
                        meta["chunk_strategy"] = "terraform_plan"
                        meta["start_char"] = abs_start
                        meta["end_char"] = abs_end
                        meta["terraform_plan_preamble"] = True
                        meta.setdefault("doc_type_kwd", "terraform")
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
                    meta["chunk_strategy"] = "terraform_plan"
                    meta["start_char"] = abs_start
                    meta["end_char"] = abs_end
                    meta.setdefault("doc_type_kwd", "terraform")
                    meta["terraform_address"] = blk.address
                    meta["terraform_action"] = blk.action
                    meta["terraform_change_index"] = int(blk.index)
                    meta["terraform_change_count"] = int(len(blocks))
                    out.append(Document(page_content=sd.page_content, metadata=meta))

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
