"""
Terraform plan output aware chunking strategy.

Targets `terraform plan` / `terraform apply` text output and splits by resource
change blocks (lines like "# aws_instance.example will be created") while
preserving character offsets.
"""


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


_PLAN_HINT_RE = re.compile(r"(?i)terraform\s+will\s+perform\s+the\s+following\s+actions|^\s*Plan:\s*\d+", re.MULTILINE)


def _parse_change_line(line: str) -> tuple[str, str] | None:
    """
    Parse a change header line like:
      # aws_instance.example will be created

    We intentionally avoid regex to prevent catastrophic-backtracking hotspots.
    """
    s = str(line or "").strip()
    if not s:
        return None
    s = s.lstrip()
    if not s.startswith("#"):
        return None
    rest = s[1:].strip()
    marker = " will be "
    idx = rest.find(marker)
    if idx <= 0:
        return None
    addr = rest[:idx].strip()
    action = rest[idx + len(marker) :].strip()
    if not addr or not action:
        return None
    return addr, action


def _build_change_blocks(text: str) -> list[_ChangeBlock]:
    raw = text or ""
    if not raw:
        return []

    starts: list[int] = []
    addrs: list[str] = []
    actions: list[str] = []
    offset = 0
    for raw_line in raw.splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        parsed = _parse_change_line(raw_line)
        if not parsed:
            continue
        addr, action = parsed
        starts.append(int(line_start))
        addrs.append(addr)
        actions.append(action)

    if not starts:
        return []
    blocks: list[_ChangeBlock] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(raw)
        addr = (addrs[idx] or "").strip()[:300]
        action = (actions[idx] or "").strip()[:80]
        blocks.append(_ChangeBlock(start=int(start), end=int(end), index=int(idx), address=addr, action=action))
    return blocks


def looks_like_terraform_plan(text: str) -> bool:
    if not text or len(text) < 120:
        return False
    head = text[:200000]
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

    def _append_split_chunks(
        self,
        out: list[Document],
        *,
        text: str,
        base_meta: dict[str, Any],
        start_offset: int,
        extra_meta: dict[str, Any],
    ) -> None:
        split_docs = self._fallback_splitter.create_documents(texts=[text], metadatas=[base_meta])
        for sd in split_docs:
            sd_meta = dict(sd.metadata or {})
            local_start = sd_meta.pop("start_index", None) or 0
            abs_start = start_offset + int(local_start)
            abs_end = abs_start + len(sd.page_content)
            meta: dict[str, Any] = dict(base_meta)
            meta.update(sd_meta)
            meta["chunk_strategy"] = "terraform_plan"
            meta["start_char"] = abs_start
            meta["end_char"] = abs_end
            meta.setdefault("doc_type_kwd", "terraform")
            meta.update(extra_meta)
            out.append(Document(page_content=sd.page_content, metadata=meta))

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            blocks = _build_change_blocks(text)
            if not blocks:
                self._append_split_chunks(
                    out,
                    text=text,
                    base_meta=base_meta,
                    start_offset=0,
                    extra_meta={"terraform_plan_fallback": True},
                )
                continue

            first = blocks[0]
            if first.start > 0:
                pre = text[: first.start]
                if pre.strip():
                    self._append_split_chunks(
                        out,
                        text=pre,
                        base_meta=base_meta,
                        start_offset=0,
                        extra_meta={"terraform_plan_preamble": True},
                    )

            for blk in blocks:
                blk_text = text[blk.start : blk.end]
                if not blk_text.strip():
                    continue
                self._append_split_chunks(
                    out,
                    text=blk_text,
                    base_meta=base_meta,
                    start_offset=blk.start,
                    extra_meta={
                        "terraform_address": blk.address,
                        "terraform_action": blk.action,
                        "terraform_change_index": int(blk.index),
                        "terraform_change_count": int(len(blocks)),
                    },
                )

        for idx, chunk in enumerate(out):
            meta = dict(chunk.metadata or {})
            meta["chunk_index"] = idx
            chunk.metadata = meta

        return out
