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
from enum import Enum
from typing import Any, Mapping


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


_FENCED_CODE_RE = re.compile(r"(?m)^\s*(```|~~~)")
_NUMBERED_LIST_RE = re.compile(r"(?m)^\s*\d{1,3}[.)]\s+\S")
_QA_RE = re.compile(r"(?im)^\s*Q[:：]\s+.+\n\s*A[:：]\s+.+", flags=re.M)

# Markdown tables: header row + separator row (GitHub-flavored markdown).
_MD_TABLE_ROW_RE = re.compile(r"(?m)^\s*\|?.+\|.+\|?\s*$")
_MD_TABLE_SEP_RE = re.compile(r"(?m)^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _header_text(meta: Mapping[str, Any]) -> str:
    raw = meta.get("header_path") or meta.get("header_context") or ""
    if not isinstance(raw, str):
        raw = str(raw or "")
    return raw.strip()


def _looks_like_markdown_table(text: str) -> bool:
    if not text:
        return False
    # Fast-path: need at least one separator line.
    sep_match = _MD_TABLE_SEP_RE.search(text)
    if not sep_match:
        return False
    # Ensure there's a plausible header row near the separator.
    before = text[: sep_match.start()]
    # Look at last few lines before the separator.
    head_lines = before.splitlines()[-4:]
    for ln in reversed(head_lines):
        if _MD_TABLE_ROW_RE.match(ln):
            return True
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
        if any(k in header for k in ("definition", "definitions", "glossary", "terminology", "定义", "术语", "名词解释")):
            return ChunkSemanticRole.DEFINITION.value
        if any(k in header for k in ("procedure", "procedures", "step", "steps", "how to", "usage", "install", "setup", "步骤", "流程", "使用", "操作", "指南")):
            return ChunkSemanticRole.PROCEDURE.value
        if any(k in header for k in ("policy", "policies", "compliance", "privacy", "security", "政策", "合规", "隐私", "安全")):
            return ChunkSemanticRole.POLICY.value
        if any(k in header for k in ("example", "examples", "sample", "samples", "demo", "示例", "样例", "例子")):
            return ChunkSemanticRole.EXAMPLE.value
        if any(k in header for k in ("reference", "appendix", "resources", "api reference", "参考", "附录", "资源")):
            return ChunkSemanticRole.REFERENCE.value

    # Content-based fallbacks (keep conservative).
    if _QA_RE.search(text):
        return ChunkSemanticRole.FAQ.value
    if len(_NUMBERED_LIST_RE.findall(text)) >= 2:
        return ChunkSemanticRole.PROCEDURE.value

    return ChunkSemanticRole.UNKNOWN.value


__all__ = ["ChunkSemanticRole", "classify_chunk_semantic_role"]

