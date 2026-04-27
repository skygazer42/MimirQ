"""
Chunk semantic role labeling (deterministic heuristics).

Why:
- Retrieval and reranking benefit from lightweight, explainable chunk "roles"
  (definition/procedure/policy/example/table/code/faq/reference/unknown).
- Keep this deterministic and dependency-free (no LLM by default).

Notes:
- This is intentionally separate from existing `chunk_role` which is used for
  structural roles (parent/child/qa/etc).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import Enum
from typing import Any


class ChunkSemanticRole(str, Enum):
    DEFINITION = "definition"
    PROCEDURE = "procedure"
    POLICY = "policy"
    EXAMPLE = "example"
    TABLE = "table"
    CODE = "code"
    FAQ = "faq"
    REFERENCE = "reference"
    UNKNOWN = "unknown"


class ChunkType(str, Enum):
    TEXT = "text"
    FORMULA = "formula"
    TABLE = "table"
    CODE = "code"
    FIGURE = "figure"
    CHART_DATA = "chart_data"
    SEAL = "seal"


_FENCED_CODE_RE = re.compile(r"(?m)^\s*(```|~~~)")
_NUMBERED_LIST_RE = re.compile(r"(?m)^\s*\d{1,3}[.)]\s+\S")


def _header_text(meta: Mapping[str, Any]) -> str:
    raw = meta.get("header_path") or meta.get("header_context") or ""
    if not isinstance(raw, str):
        raw = str(raw)
    return raw.strip()


_MD_TABLE_SEP_ALLOWED = frozenset("-:")


def _looks_like_qa_pair(text: str) -> bool:
    if not text:
        return False
    lines = (text or "").splitlines()
    if len(lines) < 2:
        return False

    def is_marker(line: str, *, marker: str) -> bool:
        s = (line or "").lstrip()
        if len(s) < 3:
            return False
        if s[0].lower() != marker.lower():
            return False
        if s[1] not in (":", "："):
            return False
        return bool(s[2:].strip())

    for i in range(len(lines) - 1):
        if is_marker(lines[i], marker="q") and is_marker(lines[i + 1], marker="a"):
            return True
    return False


def _split_md_table_cells(line: str) -> list[str]:
    s = (line or "").strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_md_table_separator_row(line: str) -> bool:
    s = (line or "").strip()
    if "|" not in s:
        return False
    cells = _split_md_table_cells(s)
    if len(cells) < 2:
        return False
    for cell in cells:
        if len(cell) < 2:
            return False
        if any(ch not in _MD_TABLE_SEP_ALLOWED for ch in cell):
            return False
        if cell.count("-") < 2:
            return False
    return True


def _is_md_table_header_row(line: str) -> bool:
    s = (line or "").strip()
    if "|" not in s:
        return False
    if _is_md_table_separator_row(s):
        return False
    cells = _split_md_table_cells(s)
    if len(cells) < 2:
        return False
    # Require at least one non-empty cell.
    return any(cells)


def _looks_like_markdown_table(text: str) -> bool:
    if not text:
        return False
    lines = (text or "").splitlines()
    for idx, ln in enumerate(lines):
        if not _is_md_table_separator_row(ln):
            continue
        # Look at last few lines before the separator.
        start = max(0, idx - 4)
        for prev in range(idx - 1, start - 1, -1):
            if _is_md_table_header_row(lines[prev]):
                return True
        return False
    return False


def classify_chunk_semantic_role(*, content: str, meta: Mapping[str, Any] | None = None) -> str:
    """
    Classify chunk role for retrieval/reranking (best-effort).

    Returns one of ChunkSemanticRole values.
    """
    meta = meta or {}

    existing = meta.get("chunk_semantic_role")
    if isinstance(existing, str):
        existing_norm = existing.strip().lower()
        if existing_norm in {r.value for r in ChunkSemanticRole}:
            return existing_norm

    chunk_role = str(meta.get("chunk_role") or "").strip().lower()
    if chunk_role == "qa":
        return ChunkSemanticRole.FAQ.value

    strategy = str(meta.get("chunk_strategy") or "").strip().lower()
    if strategy == "glossary":
        return ChunkSemanticRole.DEFINITION.value
    if strategy == "sop_steps":
        return ChunkSemanticRole.PROCEDURE.value
    if strategy in {"markdown_table", "csv_rows", "spreadsheet_sheet"}:
        return ChunkSemanticRole.TABLE.value

    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    if doc_type == "table":
        return ChunkSemanticRole.TABLE.value

    text = str(content or "")
    if _FENCED_CODE_RE.search(text):
        return ChunkSemanticRole.CODE.value
    if _looks_like_markdown_table(text):
        return ChunkSemanticRole.TABLE.value

    header = _header_text(meta).lower()
    if header:
        # Order matters: prefer narrow/binary labels over broad ones.
        if any(k in header for k in ("faq", "frequently asked", "常见问题")):
            return ChunkSemanticRole.FAQ.value
        if any(
            k in header for k in ("definition", "definitions", "glossary", "terminology", "定义", "术语", "名词解释")
        ):
            return ChunkSemanticRole.DEFINITION.value
        if any(
            k in header
            for k in (
                "procedure",
                "procedures",
                "step",
                "steps",
                "how to",
                "usage",
                "install",
                "setup",
                "步骤",
                "流程",
                "使用",
                "操作",
                "指南",
            )
        ):
            return ChunkSemanticRole.PROCEDURE.value
        if any(
            k in header
            for k in ("policy", "policies", "compliance", "privacy", "security", "政策", "合规", "隐私", "安全")
        ):
            return ChunkSemanticRole.POLICY.value
        if any(k in header for k in ("example", "examples", "sample", "samples", "demo", "示例", "样例", "例子")):
            return ChunkSemanticRole.EXAMPLE.value
        if any(k in header for k in ("reference", "appendix", "resources", "api reference", "参考", "附录", "资源")):
            return ChunkSemanticRole.REFERENCE.value

    # Content-based fallbacks (keep conservative).
    if _looks_like_qa_pair(text):
        return ChunkSemanticRole.FAQ.value
    if len(_NUMBERED_LIST_RE.findall(text)) >= 2:
        return ChunkSemanticRole.PROCEDURE.value

    return ChunkSemanticRole.UNKNOWN.value


def classify_chunk_type(*, content: str, meta: Mapping[str, Any] | None = None) -> str:
    meta = meta or {}

    existing = meta.get("chunk_type")
    if isinstance(existing, str):
        existing_norm = existing.strip().lower()
        if existing_norm in {r.value for r in ChunkType}:
            return existing_norm

    content_type = str(meta.get("content_type") or "").strip().lower()
    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    visual_kind = str(meta.get("visual_kind") or "").strip().lower()
    text = str(content or "")
    semantic_role = str(meta.get("chunk_semantic_role") or "").strip().lower()

    if "Chart data:" in text or content_type == "chart_data":
        return ChunkType.CHART_DATA.value
    if content_type in {"formula", "formula_ocr"} or doc_type in {"formula", "formula_ocr"}:
        return ChunkType.FORMULA.value
    if doc_type == "seal" or content_type == "seal" or isinstance(meta.get("seal_primary"), dict):
        return ChunkType.SEAL.value
    if _FENCED_CODE_RE.search(text) or semantic_role == ChunkSemanticRole.CODE.value:
        return ChunkType.CODE.value
    if _looks_like_markdown_table(text) or semantic_role == ChunkSemanticRole.TABLE.value:
        return ChunkType.TABLE.value
    if visual_kind in {"chart", "diagram", "figure"} or doc_type == "image":
        return ChunkType.FIGURE.value
    if semantic_role == ChunkSemanticRole.TABLE.value:
        return ChunkType.TABLE.value
    return ChunkType.TEXT.value


def build_chunk_type_subindex_payload(
    *,
    chunk_id: str,
    content: str,
    meta: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    resolved_chunk_id = str(chunk_id or "").strip()
    chunk_type = classify_chunk_type(content=content, meta=meta)
    return {
        "schema": "mimirq.chunk_type_subindex.v1",
        "chunk_id": resolved_chunk_id,
        "chunk_type": chunk_type,
        "subindex_key": chunk_type,
        "subindex_id": f"{resolved_chunk_id}@{chunk_type}",
    }


__all__ = [
    "ChunkSemanticRole",
    "ChunkType",
    "build_chunk_type_subindex_payload",
    "classify_chunk_semantic_role",
    "classify_chunk_type",
]
