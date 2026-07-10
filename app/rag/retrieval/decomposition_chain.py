"""Deterministic helpers for chained query decomposition retrieval."""


from typing import Any


def summarize_chain_step(citations: list[dict[str, Any]]) -> str:
    """Summarize one retrieval step into a compact, reusable finding string."""
    parts: list[str] = []
    for item in citations[:3]:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or item.get("document_id") or "").strip()
        snippet = " ".join(str(item.get("snippet") or "").split()).strip()
        if source and snippet:
            parts.append(f"{source}: {snippet[:160]}")
        elif snippet:
            parts.append(snippet[:160])
        elif source:
            parts.append(source[:120])
    return " | ".join(parts)[:500].strip()


def build_chained_query(subquestion: str, prior_findings: list[str]) -> str:
    """Build the next retrieval query using the current subquestion plus prior findings."""
    base = " ".join(str(subquestion or "").split()).strip()
    if not base:
        return ""

    cleaned_findings: list[str] = []
    seen: set[str] = set()
    for finding in prior_findings[-3:]:
        normalized = " ".join(str(finding or "").split()).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned_findings.append(normalized[:220])

    if not cleaned_findings:
        return base

    query = base + "\n\nPrior findings:\n" + "\n".join(f"- {item}" for item in cleaned_findings)
    if len(query) > 900:
        query = query[:897] + "..."
    return query


__all__ = ["build_chained_query", "summarize_chain_step"]
