from __future__ import annotations

import re
from typing import Any

from app.core.config import settings
from app.rag.core.text import split_into_claims, verify_claim_with_fallback
from app.rag.workflows.base import BaseWorkflow, WorkflowMode, WorkflowResult

_STYLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("prescriptive_language", re.compile(r"\bmust\b|必须|务必|应当", flags=re.IGNORECASE)),
    ("urgent_language", re.compile(r"\bimmediately\b|\basap\b|\bright away\b|立即|马上", flags=re.IGNORECASE)),
    ("absolute_language", re.compile(r"\balways\b|\bnever\b|\bdefinitely\b|\bcertainly\b|\bguaranteed\b|总是|绝不|一定", flags=re.IGNORECASE)),
)


def _detect_style_issues(answer: str) -> list[dict[str, str]]:
    raw = str(answer or "").strip()
    if not raw:
        return []

    issues: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for code, pattern in _STYLE_RULES:
        match = pattern.search(raw)
        if match is None:
            continue
        span = str(match.group(0) or "").strip()
        if not span:
            continue
        key = (code, span.casefold() if span.isascii() else span)
        if key in seen:
            continue
        seen.add(key)
        issues.append({"code": code, "span": span})
    return issues


def run_critic_review(
    *,
    question: str,
    answer: str,
    evidence_text: str,
    citations: list[dict[str, Any]] | None = None,
    max_claims: int | None = None,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
) -> dict[str, Any]:
    del question  # Reserved for future relevance-aware checks; keep the helper contract stable.

    raw_answer = str(answer or "").strip()
    evidence_raw = str(evidence_text or "").strip()
    claims = split_into_claims(
        raw_answer,
        max_claims=int(max_claims or getattr(settings, "FAITHFULNESS_SCORE_MAX_CLAIMS", 24) or 24),
    )

    claim_results: list[dict[str, Any]] = []
    unsupported_claims: list[str] = []
    supported_claims = 0
    for claim in claims:
        text = str(claim or "").strip()
        if not text:
            continue
        verification = verify_claim_with_fallback(
            text,
            evidence_raw,
            verifier_mode=verifier_mode,
            verifier_enable_contradiction_check=bool(verifier_enable_contradiction_check),
        )
        if bool(verification.supported):
            supported_claims += 1
        elif len(unsupported_claims) < 16:
            unsupported_claims.append(text[:300])
        claim_results.append(
            {
                "text": text[:300],
                "supported": bool(verification.supported),
                "reason_code": str((verification.diagnostics or {}).get("reason_code") or "unsupported"),
            }
        )

    total_claims = len(claim_results)
    faithfulness_score = round(float(supported_claims) / float(total_claims), 4) if total_claims > 0 else None
    citation_missing = len(citations or []) <= 0
    style_issues = _detect_style_issues(raw_answer)

    reason_codes: list[str] = []
    if unsupported_claims:
        reason_codes.append("unsupported_claims")
    if citation_missing:
        reason_codes.append("missing_citations")
    if style_issues:
        reason_codes.append("style_violation")

    verdict = "accept"
    if not raw_answer or unsupported_claims or citation_missing:
        verdict = "revise"

    return {
        "schema": "mimirq.critic_review.v1",
        "verdict": verdict,
        "faithfulness_score": faithfulness_score,
        "supported_claims": int(supported_claims),
        "total_claims": int(total_claims),
        "unsupported_claims": unsupported_claims,
        "claims": claim_results,
        "citation_count": int(len(citations or [])),
        "citation_missing": bool(citation_missing),
        "style_issues": style_issues,
        "reason_codes": reason_codes,
    }


class CriticWorkflow(BaseWorkflow):
    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.EVALUATOR

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        question = str(state.get("question") or state.get("query") or "").strip()
        answer = str(state.get("answer") or "").strip()
        if not answer:
            return self.create_result(state, success=False, error="critic_answer_missing")

        evidence_text = str(state.get("evidence_text") or state.get("context") or "").strip()
        citations = list(state.get("citations") or [])
        critique = run_critic_review(
            question=question,
            answer=answer,
            evidence_text=evidence_text,
            citations=citations,
        )
        next_state = dict(state)
        next_state["critique"] = critique
        return self.create_result(
            next_state,
            success=True,
            metadata={
                "critic_verdict": critique.get("verdict"),
                "critic_reason_codes": list(critique.get("reason_codes") or []),
            },
        )


__all__ = ["CriticWorkflow", "run_critic_review"]
