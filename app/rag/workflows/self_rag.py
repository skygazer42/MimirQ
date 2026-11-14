import re
from typing import Any, TypedDict

from app.rag.core.faithfulness import compute_faithfulness_score


class SelfRagReflection(TypedDict):
    schema: str
    need_retrieval: bool
    is_relevant: bool
    is_supported: bool
    is_useful: bool
    verdict: str
    faithfulness_score: float | None
    supported_claims: int
    total_claims: int
    unsupported_claims: list[str]
    citation_count: int
    reason_codes: list[str]


_QUESTION_TOKEN_RE = re.compile(r"\w+", flags=re.ASCII)
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
) -> SelfRagReflection:
    raw_question = question.strip()
    raw_answer = answer.strip()
    evidence_raw = evidence_text.strip()
    faithfulness = compute_faithfulness_score(
        answer=raw_answer,
        evidence_text=evidence_raw,
    )
    score = faithfulness["score"]
    unsupported = list(faithfulness["unsupported_claims"])
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
        "need_retrieval": need_retrieval,
        "is_relevant": is_relevant,
        "is_supported": is_supported,
        "is_useful": is_useful,
        "verdict": verdict,
        "faithfulness_score": score,
        "supported_claims": faithfulness["supported_claims"],
        "total_claims": faithfulness["total_claims"],
        "unsupported_claims": unsupported,
        "citation_count": citation_count,
        "reason_codes": reason_codes,
    }


__all__ = ["run_self_rag_reflection"]
