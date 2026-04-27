from __future__ import annotations

import re
from typing import Any

from app.rag.core.faithfulness import compute_faithfulness_score

_QUESTION_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_QUESTION_STOPWORDS = {
    "what",
    "how",
    "why",
    "when",
    "where",
    "which",
    "who",
    "does",
    "do",
    "did",
    "is",
    "are",
    "the",
    "a",
    "an",
    "i",
    "you",
}


def run_self_rag_reflection(
    *,
    question: str,
    answer: str,
    evidence_text: str,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_question = str(question or "").strip()
    raw_answer = str(answer or "").strip()
    evidence_raw = str(evidence_text or "").strip()
    faithfulness = compute_faithfulness_score(
        answer=raw_answer,
        evidence_text=evidence_raw,
    )
    score = faithfulness.get("score")
    unsupported = list(faithfulness.get("unsupported_claims") or [])
    citation_count = len(citations or [])

    answer_cf = raw_answer.casefold()
    evidence_cf = evidence_raw.casefold()
    question_terms = [
        token
        for token in _QUESTION_TOKEN_RE.findall(raw_question.casefold())
        if len(token) >= 4 and token not in _QUESTION_STOPWORDS
    ]
    relevant_hits = sum(1 for token in question_terms if token in answer_cf)
    is_relevant = bool(raw_answer) and (not question_terms or relevant_hits >= max(1, min(2, len(question_terms))))
    direct_support = bool(answer_cf and evidence_cf and (answer_cf in evidence_cf or evidence_cf in answer_cf))
    is_supported = bool(direct_support or (score is not None and float(score) >= 0.6 and not unsupported))
    need_retrieval = not is_supported or citation_count <= 0
    is_useful = bool(raw_answer) and is_relevant and is_supported
    verdict = "accept" if is_useful and not need_retrieval else "revise"

    reason_codes: list[str] = []
    if need_retrieval:
        reason_codes.append("need_retrieval")
    if not is_relevant:
        reason_codes.append("irrelevant_answer")
    if not is_supported:
        reason_codes.append("unsupported_claims")
    if not is_useful:
        reason_codes.append("not_useful")

    return {
        "schema": "mimirq.self_rag_reflection.v1",
        "need_retrieval": bool(need_retrieval),
        "is_relevant": bool(is_relevant),
        "is_supported": bool(is_supported),
        "is_useful": bool(is_useful),
        "verdict": verdict,
        "faithfulness_score": score,
        "supported_claims": int(faithfulness.get("supported_claims") or 0),
        "total_claims": int(faithfulness.get("total_claims") or 0),
        "unsupported_claims": unsupported,
        "citation_count": int(citation_count),
        "reason_codes": reason_codes,
    }


__all__ = ["run_self_rag_reflection"]
