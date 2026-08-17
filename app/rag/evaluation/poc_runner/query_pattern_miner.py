
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


def _record_query_tokens(
    *,
    query: str,
    token_counts: Counter[str],
    token_doc_counts: defaultdict[str, int],
) -> None:
    seen_in_query: set[str] = set()
    for token in _tokenize(query):
        token_counts[token] += 1
        if token in seen_in_query:
            continue
        token_doc_counts[token] += 1
        seen_in_query.add(token)


def _query_signals(query: str) -> list[str]:
    signals: list[str] = []
    if query.count("?") + query.count("？") >= 2:
        signals.append("multiple_question_marks")
    if any(marker in query for marker in ("另外", "同时", "以及", "并且")):
        signals.append("multi_intent_connector")
    return signals


def _build_abbreviations(token_counts: Counter[str], *, min_frequency: int) -> list[dict[str, Any]]:
    return [
        {"token": token, "count": count}
        for token, count in token_counts.most_common()
        if count >= min_frequency and _is_abbreviation(token)
    ]


def _build_keyword_scores(
    *,
    token_counts: Counter[str],
    token_doc_counts: defaultdict[str, int],
    total_docs: int,
) -> list[dict[str, Any]]:
    keyword_scores = []
    for token, count in token_counts.items():
        doc_freq = max(1, token_doc_counts[token])
        score = round(float(count) * (1.0 + math.log((total_docs + 1) / doc_freq)), 4)
        keyword_scores.append({"token": token, "score": score, "count": count})
    keyword_scores.sort(key=lambda item: (item["score"], item["count"], item["token"]), reverse=True)
    return keyword_scores


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
        _record_query_tokens(query=query, token_counts=token_counts, token_doc_counts=token_doc_counts)

        signals = _query_signals(query)
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

    abbreviations = _build_abbreviations(token_counts, min_frequency=int(abbreviation_min_frequency or 0))

    for item in abbreviations:
        glossary_candidates.append(
            {
                "token": item["token"],
                "count": item["count"],
                "source": "abbreviation_frequency",
            }
        )

    total_docs = max(1, len(rows or []))
    keyword_scores = _build_keyword_scores(
        token_counts=token_counts,
        token_doc_counts=token_doc_counts,
        total_docs=total_docs,
    )

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
