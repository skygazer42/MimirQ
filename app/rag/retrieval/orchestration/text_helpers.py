"""Lightweight text helpers for retrieval orchestration.

These mirror the small subset of ``app.rag.core.text`` used by the retrieval
orchestrator, but avoid importing the heavier claim-verification stack.
"""

import re
from typing import Any

from app.rag.core.json_text import parse_json_from_text as parse_json_from_text
from app.rag.core.retrieval_modes import normalize_retrieval_mode as normalize_retrieval_mode

_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?\n]?", flags=re.S)
_QUERY_REWRITE_TRIGGER_SUBSTRINGS = (
    "它",
    "它们",
    "他",
    "他们",
    "她",
    "她们",
    "这个",
    "这段",
    "这部分",
    "这些",
    "那",
    "那个",
    "上述",
    "上面",
    "前面",
    "之前",
    "刚才",
    "上文",
    "下文",
    "这里",
    "那里",
    "继续",
    "同上",
    "同理",
)
_AUTO_LIST_INTENT_RE = re.compile(r"(列举|有哪些|列表|对比|比较|分别|优缺点|差异|汇总|总结)", flags=re.IGNORECASE)
_AUTO_KEYWORD_HINT_RES = (
    re.compile(r"\b(?:traceback|exception|error)\b"),
    re.compile(r"stack\s*trace"),
    re.compile(r"http\s*\d{3}"),
    re.compile(r"0x[0-9a-f]{4,}"),
    re.compile(r"[a-z_][a-z0-9_]{2,}\("),
    re.compile(r"\.\w{1,5}\b"),
)


def should_rewrite_query(question: str, *, short_len: int = 12) -> bool:
    q = (question or "").strip()
    if not q:
        return False
    short_len = max(1, int(short_len or 0))
    if len(q) <= short_len:
        return True
    return any(trigger in q for trigger in _QUERY_REWRITE_TRIGGER_SUBSTRINGS)


def guess_retrieval_mode(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "hybrid"

    if _AUTO_LIST_INTENT_RE.search(q):
        return "mmr"

    q_lower = q.lower()
    if any(p.search(q_lower) for p in _AUTO_KEYWORD_HINT_RES) or "/" in q_lower or "\\" in q_lower or "::" in q_lower:
        return "keyword"

    cjk = sum(1 for ch in q if "\u4e00" <= ch <= "\u9fff")
    ascii_non_space = sum(1 for ch in q if ch.isascii() and not ch.isspace())
    if cjk == 0 and ascii_non_space > 0 and len(q) <= 40:
        return "keyword"

    return "hybrid"


def _iter_citation_dicts(citations: list[dict[str, Any]] | None):
    for citation in (citations or []) if isinstance(citations, list) else []:
        if isinstance(citation, dict):
            yield citation


def _citation_followup_identity(citation: dict[str, Any]) -> tuple[Any, Any, str]:
    document_id = citation.get("document_id")
    name = citation.get("document_name") or citation.get("source")
    key = str(document_id or name or "").strip()
    return document_id, name, key


def _skip_followup_option(key: str, seen: set[str]) -> bool:
    return not key or key in seen


def _citation_followup_option(*, document_id: Any, name: Any) -> dict[str, Any]:
    return {
        "document_id": str(document_id) if document_id is not None else None,
        "document_name": str(name) if name is not None else None,
    }


def _abstain_followup_options(citations: list[dict[str, Any]] | None, *, max_options: int) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for citation in _iter_citation_dicts(citations):
        document_id, name, key = _citation_followup_identity(citation)
        if _skip_followup_option(key, seen):
            continue
        seen.add(key)
        options.append(_citation_followup_option(document_id=document_id, name=name))
        if max_options and len(options) >= max_options:
            break
    return options


def build_abstain_followup(
    *,
    reason: str | None,
    citations: list[dict[str, Any]] | None = None,
    max_options: int = 3,
) -> dict[str, Any]:
    max_options = max(0, int(max_options or 0))
    options = _abstain_followup_options(citations, max_options=max_options)
    r = str(reason or "").strip()
    if r == "citations_lt_min":
        return {
            "type": "refine_query",
            "question": (
                "No sufficient evidence was retrieved. Please refine the question or provide more relevant documents."
            ),
            "options": [],
        }
    if r == "out_of_scope":
        return {
            "type": "refine_query",
            "question": (
                "This question appears to be outside the current knowledge base. Please add relevant "
                "materials or narrow the scope."
            ),
            "options": [],
        }
    return {
        "type": "select_document" if options else "refine_query",
        "question": "I found related materials but not enough to answer confidently. Which document should I focus on?",
        "options": options,
    }


__all__ = [
    "build_abstain_followup",
    "guess_retrieval_mode",
    "normalize_retrieval_mode",
    "parse_json_from_text",
    "should_rewrite_query",
]
