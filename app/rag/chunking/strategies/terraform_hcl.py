"""
Terraform/HCL block-aware chunking strategy.

Targets Terraform-style HCL with blocks such as:
- resource "aws_instance" "web" { ... }
- module "vpc" { ... }
- variable "region" { ... }

The chunker splits by top-level blocks (brace-aware) and preserves offsets.
"""


import re
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.rag.chunking.base import BaseChunker


@dataclass(frozen=True)
class _Block:
    start: int
    end: int
    kind: str
    labels: list[str]
    index: int


@dataclass(frozen=True)
class _Section:
    start: int
    end: int
    block: _Block | None


_BLOCK_START_RE = re.compile(
    r"(?m)^\s*(?P<kind>resource|data|module|variable|output|provider|locals|terraform)\b(?P<rest>[^\\n{]*)\{"
)
_QUOTED_RE = re.compile(r"\"([^\"]{1,120})\"")


def _find_matching_brace(text: str, start: int) -> int | None:
    brace_pos = text.find("{", start)
    if brace_pos < 0:
        return None
    depth = 0
    for i in range(brace_pos, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                if end < len(text) and text[end : end + 1] == "\n":
                    end += 1
                return end
    return None


def _parse_labels(kind: str, rest: str) -> list[str]:
    kind = (kind or "").strip().lower()
    rest = rest or ""
    quoted = [m.group(1) for m in _QUOTED_RE.finditer(rest)]
    if quoted:
        return quoted[:3]
    # For locals/terraform blocks without labels.
    return []


def _iter_blocks(text: str) -> list[_Block]:
    blocks: list[_Block] = []
    for m in _BLOCK_START_RE.finditer(text or ""):
        end = _find_matching_brace(text, m.start())
        if end is None:
            continue
        kind = (m.group("kind") or "").strip().lower()
        rest = (m.group("rest") or "").strip()
        labels = _parse_labels(kind, rest)
        blocks.append(_Block(start=m.start(), end=end, kind=kind, labels=labels, index=len(blocks)))
    return blocks


def _build_sections(text: str, blocks: list[_Block]) -> list[_Section]:
    if not blocks:
        return [_Section(start=0, end=len(text), block=None)]
    sections: list[_Section] = []
    first = blocks[0]
    if first.start > 0:
        sections.append(_Section(start=0, end=first.start, block=None))
    for idx, b in enumerate(blocks):
        start = b.start
        end = blocks[idx + 1].start if idx + 1 < len(blocks) else len(text)
        end = max(end, b.end)
        sections.append(_Section(start=start, end=end, block=b))
    return sections


def looks_like_terraform_hcl(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    head = text[:12000].lower()
    if "terraform {" in head or "provider " in head or "resource " in head:
        # Ensure braces + at least one block start.
        return _BLOCK_START_RE.search(text) is not None
    blocks = _iter_blocks(text)
    return len(blocks) >= 2


class TerraformHCLChunker(BaseChunker):
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = int(chunk_size)
        self.chunk_overlap = int(chunk_overlap)

        self._fallback_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", "}", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    def _chunk_metadata(
        self,
        *,
        base_meta: dict[str, Any],
        sd_meta: dict[str, Any],
        abs_start: int,
        abs_end: int,
        current: _Block | None,
    ) -> dict[str, Any]:
        meta: dict[str, Any] = dict(base_meta)
        meta.update(sd_meta)
        meta["chunk_strategy"] = "terraform_hcl"
        meta["start_char"] = abs_start
        meta["end_char"] = abs_end
        meta.setdefault("doc_type_kwd", "hcl")
        if current is None:
            return meta
        meta["hcl_block_type"] = current.kind
        if current.labels:
            meta["hcl_block_labels"] = current.labels
            meta["hcl_block_label"] = current.labels[0]
        if current.kind in {"resource", "data"} and len(current.labels) >= 2:
            meta["hcl_address"] = f"{current.kind}.{current.labels[0]}.{current.labels[1]}"
        elif current.kind in {"module", "variable", "output", "provider"} and current.labels:
            meta["hcl_address"] = f"{current.kind}.{current.labels[0]}"
        return meta

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            blocks = _iter_blocks(text)
            sections = _build_sections(text, blocks)

            current: _Block | None = None
            for section in sections:
                sec_text = text[section.start : section.end]
                if not sec_text.strip():
                    continue
                if section.block is not None:
                    current = section.block

                split_docs = self._fallback_splitter.create_documents(texts=[sec_text], metadatas=[base_meta])
                for sd in split_docs:
                    sd_meta = dict(sd.metadata or {})
                    local_start = sd_meta.pop("start_index", None) or 0
                    abs_start = section.start + int(local_start)
                    abs_end = abs_start + len(sd.page_content)
                    out.append(
                        Document(
                            page_content=sd.page_content,
                            metadata=self._chunk_metadata(
                                base_meta=base_meta,
                                sd_meta=sd_meta,
                                abs_start=abs_start,
                                abs_end=abs_end,
                                current=current,
                            ),
                        )
                    )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
