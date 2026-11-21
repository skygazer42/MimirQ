"""Verify claims and render citations and images in generated answers."""

import json
import logging
from typing import Any

from app.infrastructure.config import settings
from app.infrastructure.security.pii import redact_text
from app.rag.llm.citation_rendering import render_sentence_citations_inline, render_sentence_citations_markdown
from app.rag.llm.structured_output import parse_and_repair_structured_output
from app.rag.runtime.contracts import _UNABLE_TO_ANSWER_MESSAGE
from app.rag.runtime.graph.state import RAGState
from app.rag.safety.claim_evidence import build_claim_evidence_map
from app.rag.safety.claim_verification import split_into_claims, verify_claim_with_fallback
from app.rag.safety.visible_evidence import scrub_structured_output_visible_evidence_only

logger = logging.getLogger("rag.pipelines.langgraph")


def _build_structured_citations(citations: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    return [
        {
            "document_id": citation.get("document_id"),
            "chunk_id": citation.get("chunk_id"),
            "page_number": citation.get("page_number"),
            "relevance_score": citation.get("relevance_score"),
        }
        for citation in citations[: max(0, top_k)]
    ]


def _normalized_claim_verifier_mode() -> str:
    mode = str(settings.RAG_CLAIM_VERIFIER_MODE).strip().lower()
    return mode if mode in {"token_overlap", "semantic_heuristic", "strict"} else "token_overlap"


def _generation_claim_context(*, state: RAGState, ctx: str, pii_on: bool) -> dict[str, Any]:
    strict_visible = bool(settings.RAG_VISIBLE_EVIDENCE_ONLY_ENABLED) or bool(state.get("visible_evidence_only"))
    claim_check_configured = bool(settings.RAG_CLAIM_CHECK_ENABLED) or strict_visible
    claim_check_mode = "none"
    if claim_check_configured:
        claim_check_mode = "structured" if bool(state.get("structured_output")) else "text"
    return {
        "strict_visible": strict_visible,
        "claim_check_configured": claim_check_configured,
        "claim_check_mode": claim_check_mode,
        "claim_check_applied": claim_check_mode != "none",
        "claim_check_max_claims": max(1, int(settings.RAG_CLAIM_CHECK_MAX_CLAIMS)),
        "claim_verifier_mode": _normalized_claim_verifier_mode(),
        "claim_verifier_enable_contradiction_check": bool(settings.RAG_CLAIM_VERIFIER_ENABLE_CONTRADICTION_CHECK),
        "evidence_text": redact_text(ctx) if pii_on else ctx,
    }


def _claim_verifier_kwargs(claim_ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "verifier_mode": claim_ctx["claim_verifier_mode"],
        "verifier_enable_contradiction_check": claim_ctx["claim_verifier_enable_contradiction_check"],
        "use_nli_fallback": bool(settings.RAG_CLAIM_NLI_VERIFIER_ENABLED),
        "nli_provider": str(settings.RAG_CLAIM_NLI_VERIFIER_PROVIDER),
        "nli_model_name": str(settings.RAG_CLAIM_NLI_VERIFIER_MODEL),
        "nli_timeout_sec": settings.RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC,
    }


def _apply_claim_check_to_answer(
    *,
    answer: str,
    state: RAGState,
    claim_ctx: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    meta = {"claim_check_removed": 0, "claim_check_total": 0, "claim_check_removed_reasons": []}
    if not claim_ctx["claim_check_applied"]:
        return answer, meta
    if claim_ctx["claim_check_mode"] == "text":
        return _apply_text_claim_check(answer=answer, claim_ctx=claim_ctx)
    return _apply_structured_claim_check(answer=answer, state=state, claim_ctx=claim_ctx)


def _apply_text_claim_check(*, answer: str, claim_ctx: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    claims = split_into_claims(answer, max_claims=int(claim_ctx["claim_check_max_claims"]))
    kept: list[str] = []
    removed_reasons: list[dict[str, Any]] = []
    for claim in claims:
        result = verify_claim_with_fallback(
            claim,
            claim_ctx["evidence_text"],
            **_claim_verifier_kwargs(claim_ctx),
        )
        if result.supported:
            kept.append(claim)
            continue
        if len(removed_reasons) < 64:
            diag = result.diagnostics
            removed_reasons.append(
                {
                    "claim": claim[:300],
                    "reason_code": str(diag.get("reason_code") or diag.get("reason") or "unsupported")[:120],
                    "contradiction_type": (
                        str(diag.get("contradiction_type"))[:120]
                        if diag.get("contradiction_type") is not None
                        else None
                    ),
                }
            )
    cleaned = "\n".join(kept).strip() or _UNABLE_TO_ANSWER_MESSAGE
    return cleaned, {
        "claim_check_removed": max(0, len(claims) - len(kept)),
        "claim_check_total": len(claims),
        "claim_check_removed_reasons": removed_reasons,
    }


def _apply_structured_claim_check(
    *,
    answer: str,
    state: RAGState,
    claim_ctx: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    structured_citations = _build_structured_citations(
        state.get("citations") or [],
        top_k=int(state.get("top_k") or 0),
    )
    parsed, _meta = parse_and_repair_structured_output(
        answer,
        preset=state.get("structured_preset"),
        fallback_answer=_UNABLE_TO_ANSWER_MESSAGE,
        fallback_citations=structured_citations,
    )
    scrubbed, scrub_meta = scrub_structured_output_visible_evidence_only(
        parsed,
        evidence_text=claim_ctx["evidence_text"],
        max_claims=int(claim_ctx["claim_check_max_claims"]),
        **_claim_verifier_kwargs(claim_ctx),
    )
    if isinstance(scrubbed, dict) and isinstance(scrubbed.get("answer"), str) and not scrubbed["answer"].strip():
        scrubbed["answer"] = _UNABLE_TO_ANSWER_MESSAGE
    removed_reasons = []
    if isinstance(scrub_meta, dict) and isinstance(scrub_meta.get("claim_check_removed_reasons"), list):
        removed_reasons = [x for x in scrub_meta["claim_check_removed_reasons"] if isinstance(x, dict)][:64]
    return json.dumps(scrubbed, ensure_ascii=False, separators=(",", ":")), {
        "claim_check_removed": int(scrub_meta.get("claims_removed") or 0) if isinstance(scrub_meta, dict) else 0,
        "claim_check_total": int(scrub_meta.get("claims_total") or 0) if isinstance(scrub_meta, dict) else 0,
        "claim_check_removed_reasons": removed_reasons,
    }


def _build_claim_evidence_safe(
    *,
    answer: str,
    state: RAGState,
    claim_ctx: dict[str, Any],
) -> list[dict[str, Any]]:
    if state.get("structured_output"):
        return []
    try:
        return build_claim_evidence_map(
            answer,
            evidence_chunks=list(state.get("docs") or []),
            max_claims=int(claim_ctx["claim_check_max_claims"]) if claim_ctx["claim_check_configured"] else 24,
            **_claim_verifier_kwargs(claim_ctx),
        )
    except Exception as exc:
        logger.debug("Claim evidence mapping unavailable (%s)", type(exc).__name__)
        return []


def _render_generation_answer_extras(
    *,
    answer: str,
    state: RAGState,
    pii_on: bool,
    claim_ctx: dict[str, Any],
    claim_evidence: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    sentence_meta = {
        "enabled": bool(settings.SENTENCE_CITATIONS_INLINE_ENABLED),
        "style": str(settings.SENTENCE_CITATIONS_INLINE_STYLE).strip().lower() or "appendix",
        "used": False,
        "count": 0,
        "fallback_reason": None,
    }
    if sentence_meta["style"] not in {"appendix", "inline"}:
        sentence_meta["style"] = "appendix"
    answer, sentence_meta = _render_sentence_citation_variants(
        answer=answer,
        state=state,
        pii_on=pii_on,
        claim_ctx=claim_ctx,
        claim_evidence=claim_evidence,
        sentence_meta=sentence_meta,
    )
    answer = _append_related_images(answer=answer, state=state, pii_on=pii_on)
    return answer, sentence_meta


def _render_sentence_citation_variants(
    *,
    answer: str,
    state: RAGState,
    pii_on: bool,
    claim_ctx: dict[str, Any],
    claim_evidence: list[dict[str, Any]],
    sentence_meta: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if state.get("structured_output") or not sentence_meta["enabled"]:
        return answer, sentence_meta
    if sentence_meta["style"] == "inline":
        answer, sentence_meta = _render_inline_sentence_citations(
            answer=answer,
            claim_ctx=claim_ctx,
            claim_evidence=claim_evidence,
            sentence_meta=sentence_meta,
        )
    if sentence_meta["style"] == "appendix":
        answer, sentence_meta = _render_appendix_sentence_citations(
            answer=answer,
            pii_on=pii_on,
            claim_evidence=claim_evidence,
            sentence_meta=sentence_meta,
        )
    return answer, sentence_meta


def _sentence_citation_render_limits() -> dict[str, int]:
    return {
        "max_items": max(0, int(settings.SENTENCE_CITATIONS_INLINE_MAX_ITEMS)),
        "max_evidence_per_claim": max(
            1,
            int(settings.SENTENCE_CITATIONS_INLINE_MAX_EVIDENCE_PER_CLAIM),
        ),
    }


def _render_inline_sentence_citations(
    *,
    answer: str,
    claim_ctx: dict[str, Any],
    claim_evidence: list[dict[str, Any]],
    sentence_meta: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if claim_ctx["claim_check_mode"] != "text":
        sentence_meta["style"] = "appendix"
        sentence_meta["fallback_reason"] = "claim_check_not_text"
        return answer, sentence_meta
    limits = _sentence_citation_render_limits()
    inline_text, rendered_count = render_sentence_citations_inline(claim_evidence, **limits)
    if inline_text:
        sentence_meta["used"] = True
        sentence_meta["count"] = rendered_count
        return inline_text, sentence_meta
    sentence_meta["style"] = "appendix"
    sentence_meta["fallback_reason"] = "inline_render_empty"
    return answer, sentence_meta


def _render_appendix_sentence_citations(
    *,
    answer: str,
    pii_on: bool,
    claim_evidence: list[dict[str, Any]],
    sentence_meta: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    limits = _sentence_citation_render_limits()
    suffix_md, rendered_count = render_sentence_citations_markdown(claim_evidence, **limits)
    if not suffix_md:
        return answer, sentence_meta
    answer = (answer) + (redact_text(suffix_md) if pii_on else suffix_md)
    sentence_meta["used"] = True
    sentence_meta["count"] = rendered_count
    return answer, sentence_meta


def _append_related_images(*, answer: str, state: RAGState, pii_on: bool) -> str:
    if state.get("structured_output") or not settings.SHOW_IMAGE_IN_ANSWER or settings.IMAGE_APPEND_MAX <= 0:
        return answer
    image_urls = _answer_image_urls(state.get("citations") or [])
    if not image_urls:
        return answer
    parts = ["\n\n---\n\n### Related Images\n"]
    parts.extend(f"![Referenced Image {idx}]({url})" for idx, url in enumerate(image_urls, 1))
    images_md = "\n\n".join(parts) + "\n"
    return (answer) + (redact_text(images_md) if pii_on else images_md)


def _answer_image_urls(citations: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for citation in citations:
        if not citation.get("has_image"):
            continue
        url = citation.get("img_url")
        if not isinstance(url, str) or not url.strip() or url in urls:
            continue
        urls.append(url)
        if len(urls) >= settings.IMAGE_APPEND_MAX:
            break
    return urls
