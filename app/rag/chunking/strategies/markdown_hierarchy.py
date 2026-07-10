"""
Markdown hierarchy chunking strategy.

Goal: produce a lightweight, deterministic two-level hierarchy for Markdown:
paragraph -> sentence, with stable hierarchy metadata (node/parent/sibling keys).

This is intentionally "overlay-first":
- We do NOT build a separate offline tree index.
- We emit plain chunks with hierarchy metadata so retrieval-time expansion/collapse
  can treat them as a tree (similar to KohakuRAG's online behavior).
"""


from dataclasses import dataclass

from langchain_core.documents import Document

from app.rag.chunking.base import BaseChunker
from app.rag.chunking.utils.heading_parsing import parse_markdown_hash_heading
from app.rag.chunking.utils.hierarchical import hierarchical_chunk_markdown


@dataclass(frozen=True)
class _Heading:
    pos: int
    level: int
    text: str


def _iter_markdown_headings(text: str) -> list[_Heading]:
    out: list[_Heading] = []
    offset = 0
    for raw_line in (text or "").splitlines(keepends=True):
        line_start = offset
        offset += len(raw_line)
        parsed = parse_markdown_hash_heading(raw_line)
        if parsed is None:
            continue
        level, title = parsed
        if not title:
            continue
        out.append(_Heading(pos=int(line_start), level=int(level), text=str(title)[:200]))
    return out


def _update_heading_stack(stack: list[str], *, heading: _Heading) -> list[str]:
    level = max(1, min(int(heading.level), 6))
    trimmed = stack[: max(0, level - 1)]
    while len(trimmed) < level:
        trimmed.append("")
    trimmed[level - 1] = heading.text
    # Drop empty tails to keep "A > B >" clean.
    while trimmed and not str(trimmed[-1] or "").strip():
        trimmed.pop()
    return trimmed


class MarkdownHierarchyChunker(BaseChunker):
    """
    Hierarchical Markdown chunker.

    Output:
    - paragraph nodes (hierarchy_level="paragraph", hierarchy_parent_key=None)
    - sentence nodes (hierarchy_level="sentence", hierarchy_parent_key=<paragraph node key>)
    """

    def __init__(self, chunk_size: int, chunk_overlap: int):
        # Not used today (hierarchy chunking is structure-based), but keep signature
        # compatible with the factory and future tuning.
        self.chunk_size = int(chunk_size or 0)
        self.chunk_overlap = int(chunk_overlap or 0)

    def split_documents(self, documents: list[Document]) -> list[Document]:
        out: list[Document] = []

        for doc in documents:
            text = doc.page_content or ""
            base_meta = dict(doc.metadata or {})
            if not text.strip():
                continue

            data = hierarchical_chunk_markdown(text) or {}
            paragraphs = data.get("paragraphs") if isinstance(data, dict) else None
            sentences = data.get("sentences") if isinstance(data, dict) else None
            paragraphs = paragraphs if isinstance(paragraphs, list) else []
            sentences = sentences if isinstance(sentences, list) else []

            # Group sentences by paragraph id for stable output order.
            sentences_by_parent: dict[str, list[dict]] = {}
            for s in sentences:
                if not isinstance(s, dict):
                    continue
                pid = str(s.get("parent_id") or "").strip()
                if not pid:
                    continue
                sentences_by_parent.setdefault(pid, []).append(s)

            for _pid, slist in sentences_by_parent.items():
                slist.sort(key=lambda x: int(x.get("index") or 0))

            # Heading context (optional; used by embedding prefix logic).
            headings = _iter_markdown_headings(text)
            h_cursor = 0
            stack: list[str] = []

            def header_path_for(start_char: int) -> str | None:
                nonlocal h_cursor, stack
                start_i = max(0, int(start_char or 0))
                while h_cursor < len(headings) and int(headings[h_cursor].pos) <= start_i:
                    stack = _update_heading_stack(stack, heading=headings[h_cursor])
                    h_cursor += 1
                path = " > ".join([p for p in stack if str(p or "").strip()])
                return path if path else None

            # Emit paragraph then its sentence children (reading order).
            for p in paragraphs:
                if not isinstance(p, dict):
                    continue
                p_text = str(p.get("text") or "")
                if not p_text.strip():
                    continue

                start = int(p.get("start") or 0)
                end = int(p.get("end") or (start + len(p_text)))

                p_meta = dict(base_meta)
                p_meta.update(
                    {
                        "chunk_strategy": "markdown_hierarchy",
                        "chunk_role": "paragraph",
                        "start_char": start,
                        "end_char": end,
                        # Preserve hierarchy metadata emitted by the utility.
                        "hierarchy_basis": p.get("hierarchy_basis"),
                        "hierarchy_level": p.get("hierarchy_level") or "paragraph",
                        "hierarchy_node_key": p.get("hierarchy_node_key") or p.get("id"),
                        "hierarchy_family_key": p.get("hierarchy_family_key") or p.get("id"),
                        "hierarchy_parent_key": p.get("hierarchy_parent_key"),
                        "hierarchy_prev_sibling_key": p.get("hierarchy_prev_sibling_key"),
                        "hierarchy_next_sibling_key": p.get("hierarchy_next_sibling_key"),
                        "hierarchy_sibling_index": p.get("hierarchy_sibling_index"),
                        "tokens_est": p.get("tokens_est"),
                    }
                )

                hp = header_path_for(start)
                if hp:
                    p_meta.setdefault("header_path", hp)
                    p_meta.setdefault("header_context", hp)

                # Align metadata chunk_index with output order (tests rely on it).
                p_meta["chunk_index"] = len(out)
                para_doc = Document(page_content=p_text, metadata=p_meta)
                out.append(para_doc)

                sid = str(p.get("id") or p_meta.get("hierarchy_node_key") or "").strip()
                for s in sentences_by_parent.get(sid, []):
                    s_text = str(s.get("text") or "")
                    if not s_text.strip():
                        continue
                    s_start = int(s.get("start") or start)
                    s_end = int(s.get("end") or (s_start + len(s_text)))

                    s_meta = dict(base_meta)
                    s_meta.update(
                        {
                            "chunk_strategy": "markdown_hierarchy",
                            "chunk_role": "sentence",
                            "start_char": s_start,
                            "end_char": s_end,
                            "parent_id": sid,
                            "hierarchy_basis": s.get("hierarchy_basis"),
                            "hierarchy_level": s.get("hierarchy_level") or "sentence",
                            "hierarchy_node_key": s.get("hierarchy_node_key") or s.get("id"),
                            "hierarchy_family_key": s.get("hierarchy_family_key") or sid,
                            "hierarchy_parent_key": s.get("hierarchy_parent_key") or sid,
                            "hierarchy_prev_sibling_key": s.get("hierarchy_prev_sibling_key"),
                            "hierarchy_next_sibling_key": s.get("hierarchy_next_sibling_key"),
                            "hierarchy_sibling_index": s.get("hierarchy_sibling_index"),
                            "tokens_est": s.get("tokens_est"),
                        }
                    )
                    if hp:
                        s_meta.setdefault("header_path", hp)
                        s_meta.setdefault("header_context", hp)

                    s_meta["chunk_index"] = len(out)
                    out.append(Document(page_content=s_text, metadata=s_meta))

        return out


__all__ = ["MarkdownHierarchyChunker"]
