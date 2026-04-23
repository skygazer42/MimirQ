from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.rag.tools.web_search import web_search


def classify_retrieval_verdict(
    retrieval_result: dict[str, Any],
    *,
    min_citations: int,
    min_top_score: float,
) -> str:
    if bool(retrieval_result.get("abstain_triggered")):
        return "incorrect"
    citations = retrieval_result.get("citations") or []
    metrics = retrieval_result.get("metrics") or {}
    try:
        top_score = float(metrics.get("top_relevance_score") or 0.0)
    except Exception:
        top_score = 0.0
    if len(citations) >= max(1, int(min_citations or 1)) and top_score >= float(min_top_score or 0.0):
        return "correct"
    return "incorrect"


def format_web_search_context_block(search_result: dict[str, Any]) -> str:
    provider = str(search_result.get("provider") or "").strip() or "unknown"
    results = search_result.get("results") or []
    lines = [f"[Web Search Fallback | provider={provider}]"]
    for idx, item in enumerate(results, 1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if title:
            lines.append(f"{idx}. {title}")
        if url:
            lines.append(url)
        if snippet:
            lines.append(snippet)
    return "\n".join(lines).strip()


async def run_crag_streaming(
    *,
    question: str,
    retrieval_result: dict[str, Any],
    query_for_retrieval: str | None = None,
    max_results: int | None = None,
    site_filter: list[str] | None = None,
    freshness: str | None = None,
    lang: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    min_citations = max(1, int(getattr(settings, "RAG_CRAG_STREAMING_MIN_CITATIONS", 1) or 1))
    min_top_score = float(getattr(settings, "RAG_CRAG_STREAMING_MIN_TOP_SCORE", 0.35) or 0.35)
    verdict = classify_retrieval_verdict(
        retrieval_result,
        min_citations=min_citations,
        min_top_score=min_top_score,
    )

    if not bool(getattr(settings, "RAG_CRAG_STREAMING_ENABLED", False)) or verdict != "incorrect":
        return {
            "used": False,
            "verdict": verdict,
            "provider": None,
            "web_result_count": 0,
            "context_block": "",
            "search_result": None,
        }

    search_query = str(query_for_retrieval or question or "").strip()
    search_result = await web_search(
        search_query,
        max_results=max_results or int(getattr(settings, "RAG_CRAG_STREAMING_MAX_RESULTS", 5) or 5),
        site_filter=site_filter,
        freshness=freshness,
        lang=lang,
        region=region,
    )
    context_block = format_web_search_context_block(search_result)
    return {
        "used": bool(search_result.get("ok")) and bool(search_result.get("results")),
        "verdict": verdict,
        "provider": search_result.get("provider"),
        "web_result_count": int(search_result.get("total_results") or 0),
        "context_block": context_block,
        "search_result": search_result,
    }


__all__ = ["classify_retrieval_verdict", "format_web_search_context_block", "run_crag_streaming"]
