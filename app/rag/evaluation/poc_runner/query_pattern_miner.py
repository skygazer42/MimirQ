from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]+|[\u4e00-\u9fff]{1,8}")


def _tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN_RE.findall(text or "") if token]


def _is_abbreviation(token: str) -> bool:
    compact = str(token or "").strip()
    if not compact:
        return False
    if len(compact) <= 4:
        return True
    return compact.isdigit() and len(compact) <= 6


def mine_query_patterns(
    rows: list[dict[str, Any]],
    *,
    abbreviation_min_frequency: int = 5,
    top_k_keywords: int = 20,
) -> dict[str, Any]:
    token_counts: Counter[str] = Counter()
    doc_counts: Counter[str] = Counter()
    token_doc_counts: defaultdict[str, int] = defaultdict(int)
    glossary_candidates: list[dict[str, Any]] = []
    multi_intent_queries: list[dict[str, Any]] = []

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        query = str(row.get("original_query") or "").strip()
        if not query:
            continue
        tokens = _tokenize(query)
        seen_in_query: set[str] = set()
        for token in tokens:
            token_counts[token] += 1
            if token not in seen_in_query:
                token_doc_counts[token] += 1
                seen_in_query.add(token)

        signals: list[str] = []
        if query.count("?") + query.count("？") >= 2:
            signals.append("multiple_question_marks")
        if any(marker in query for marker in ("另外", "同时", "以及", "并且")):
            signals.append("multi_intent_connector")
        if signals:
            multi_intent_queries.append(
                {
                    "interaction_id": str(row.get("interaction_id") or ""),
                    "query": query,
                    "signals": signals,
                }
            )

        for filename in row.get("final_context_filenames") or []:
            name = str(filename or "").strip()
            if name:
                doc_counts[name] += 1

    abbreviations = [
        {"token": token, "count": count}
        for token, count in token_counts.most_common()
        if count >= int(abbreviation_min_frequency or 0) and _is_abbreviation(token)
    ]

    for item in abbreviations:
        glossary_candidates.append(
            {
                "token": item["token"],
                "count": item["count"],
                "source": "abbreviation_frequency",
            }
        )

    total_docs = max(1, len(rows or []))
    keyword_scores = []
    for token, count in token_counts.items():
        doc_freq = max(1, token_doc_counts[token])
        score = round(float(count) * (1.0 + math.log((total_docs + 1) / doc_freq)), 4)
        keyword_scores.append({"token": token, "score": score, "count": count})
    keyword_scores.sort(key=lambda item: (item["score"], item["count"], item["token"]), reverse=True)

    document_heat = [
        {"filename": filename, "count": count}
        for filename, count in doc_counts.most_common()
    ]

    return {
        "abbreviations": abbreviations,
        "glossary_candidates": glossary_candidates,
        "multi_intent_queries": multi_intent_queries,
        "document_heat": document_heat,
        "keyword_scores": keyword_scores[: max(1, int(top_k_keywords or 1))],
    }
