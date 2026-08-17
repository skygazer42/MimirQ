"""Answer generation phases for standard RAG streaming."""

import json
import time
from collections.abc import AsyncGenerator
from typing import Any

from app.core.config import settings
from app.rag.engine_support.standard_stream_state import (
    StandardStreamState,
    StreamOperation,
)


async def prepare_generation(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    # Step 4: Stream answer generation.
    runtime.data.full_response = ""
    runtime.data.gen_start = time.time()
    runtime.data.pii_on = bool(runtime.module.pii_redaction_enabled())

    runtime.data.claim_check_configured = bool(getattr(settings, "RAG_CLAIM_CHECK_ENABLED", False)) or bool(
        runtime.data.strict_visible
    )
    runtime.data.claim_check_max_claims = max(1, int(getattr(settings, "RAG_CLAIM_CHECK_MAX_CLAIMS", 24) or 24))
    runtime.data.claim_verifier_mode = (
        str(getattr(settings, "RAG_CLAIM_VERIFIER_MODE", "token_overlap") or "token_overlap").strip().lower()
    )
    if runtime.data.claim_verifier_mode not in {"token_overlap", "semantic_heuristic", "strict"}:
        runtime.data.claim_verifier_mode = "token_overlap"
    runtime.data.claim_verifier_enable_contradiction_check = bool(
        getattr(settings, "RAG_CLAIM_VERIFIER_ENABLE_CONTRADICTION_CHECK", True)
    )
    runtime.data.claim_check_mode = "none"
    if bool(runtime.data.claim_check_configured):
        # For structured output we keep the JSON shape and only scrub natural-language fields.
        runtime.data.claim_check_mode = "structured" if bool(runtime.data.structured_output) else "text"
    runtime.data.claim_check_applied = runtime.data.claim_check_mode != "none"
    runtime.data.claim_check_removed = 0
    runtime.data.claim_check_total = 0
    runtime.data.claim_check_removed_reasons: list[dict[str, Any]] = []

    runtime.data.context_for_model = (
        runtime.module.redact_text(runtime.data.context) if runtime.data.pii_on else runtime.data.context
    )
    runtime.data.history_for_model = (
        runtime.module.redact_text(runtime.data.history_text) if runtime.data.pii_on else runtime.data.history_text
    )
    runtime.data.question_for_model = (
        runtime.module.redact_text(runtime.data.question) if runtime.data.pii_on else runtime.data.question
    )

    # PII redaction must see the complete response before any bytes are
    # emitted; bounded holdbacks cannot safely cover variable-length
    # emails, secrets, or overlapping numeric identifiers.
    runtime.data.buffered_parts: list[str] | None = (
        [] if (runtime.data.claim_check_applied or runtime.data.output_guard_enabled or runtime.data.pii_on) else None
    )
    runtime.data.generation_inputs = {
        "context": runtime.data.context_for_model,
        "history": runtime.data.history_for_model,
        "question": runtime.data.question_for_model,
        "format_instructions": runtime.data.format_instructions,
    }
    runtime.data.generation_status = runtime.engine._build_stream_status_event(
        stage="generation",
        state="running",
        message="正在生成回答...",
        attempt=runtime.data.corrective_attempt_count,
        max_attempts=runtime.data.corrective_max_attempts,
    )
    if runtime.data.generation_status is not None:
        yield runtime.data.generation_status

    runtime.data.source_identification_answer_used = False

    async def _single_token_stream(text: str):  # noqa: ANN202
        yield text

    # Optional: Vision-native generation path (direct VLM answer generation).
    runtime.data.token_stream = None
    runtime.data.deterministic_source_answer = None
    if not runtime.data.structured_output:
        runtime.data.deterministic_source_answer = runtime.module.maybe_build_source_identification_answer(
            question=runtime.data.question,
            docs=runtime.data.docs,
        )
    if runtime.data.deterministic_source_answer:
        runtime.data.source_identification_answer_used = True
        runtime.data.source_answer_text = (
            runtime.module.redact_text(str(runtime.data.deterministic_source_answer))
            if runtime.data.pii_on
            else str(runtime.data.deterministic_source_answer)
        )
        runtime.data.token_stream = _single_token_stream(runtime.data.source_answer_text)


def _vision_generation_skip_meta(runtime: StandardStreamState) -> dict[str, Any] | None:
    if runtime.data.source_identification_answer_used:
        return {"enabled": False, "used": False, "reason": "source_identification_answer"}
    if not runtime.data.vision_gen_enabled:
        return {"enabled": False, "used": False, "reason": "VISION_RAG_GENERATION_ENABLED=false"}
    if not getattr(settings, "VISION_LLM_ENABLED", False):
        return {"enabled": True, "used": False, "reason": "VISION_LLM_ENABLED=false"}
    if str(runtime.data.multimodal_modality or "text").strip().lower() != "image":
        return {
            "enabled": True,
            "used": False,
            "reason": f"skipped_modality:{runtime.data.multimodal_modality}",
        }
    if not runtime.data.image_docs:
        return {"enabled": True, "used": False, "reason": "no_image_docs"}
    return None


def _vision_message_role(message: Any) -> str:
    role = str(getattr(message, "type", "") or "").strip().lower()
    if role == "human":
        return "user"
    if role == "ai":
        return "assistant"
    return role if role == "system" else "user"


def _render_vision_messages(runtime: StandardStreamState) -> list[dict[str, Any]]:
    try:
        rendered_messages = runtime.data.current_prompt_template.format_messages(**runtime.data.generation_inputs)
    except Exception:
        rendered_messages = []
    return [
        {"role": _vision_message_role(message), "content": getattr(message, "content", "")}
        for message in rendered_messages
    ]


def _attach_vision_blocks(runtime: StandardStreamState) -> None:
    attached = False
    for index in range(len(runtime.data.openai_msgs) - 1, -1, -1):
        if str(runtime.data.openai_msgs[index].get("role") or "") != "user":
            continue
        content = runtime.data.openai_msgs[index].get("content")
        parts = list(content) if isinstance(content, list) else [{"type": "text", "text": str(content or "")}]
        parts.extend(runtime.data.blocks)
        runtime.data.openai_msgs[index]["content"] = parts
        attached = True
        break
    if not attached:
        runtime.data.openai_msgs.append(
            {"role": "user", "content": [{"type": "text", "text": ""}] + runtime.data.blocks}
        )


async def prepare_vision_generation(runtime: StandardStreamState) -> None:
    try:
        runtime.data.vision_gen_enabled = bool(getattr(settings, "VISION_RAG_GENERATION_ENABLED", False))
        skip_meta = _vision_generation_skip_meta(runtime)
        if skip_meta is not None:
            runtime.data.vision_generation_meta.update(skip_meta)
            return
        runtime.data.max_images = max(0, int(getattr(settings, "VISION_RAG_GENERATION_MAX_IMAGES", 2) or 2))
        runtime.data.max_bytes = max(
            1, int(getattr(settings, "VISION_RAG_GENERATION_MAX_IMAGE_BYTES", 3_000_000) or 3_000_000)
        )
        runtime.data.blocks, runtime.data.blocks_meta = await runtime.module.build_vision_image_blocks(
            image_docs=runtime.data.image_docs,
            tenant_id=runtime.data.tenant_id,
            max_images=runtime.data.max_images,
            max_image_bytes=runtime.data.max_bytes,
        )
        runtime.data.vision_generation_meta.update(
            {
                "enabled": True,
                "used": False,
                "reason": "no_images_loaded",
                "image_blocks": runtime.data.blocks_meta,
                "max_images": int(runtime.data.max_images),
                "max_image_bytes": int(runtime.data.max_bytes),
                "model": str(getattr(settings, "VISION_LLM_MODEL", "") or "").strip() or None,
            }
        )
        if runtime.data.blocks:
            runtime.data.openai_msgs = _render_vision_messages(runtime)
            _attach_vision_blocks(runtime)
            runtime.data.vision_generation_meta.update(
                {"used": True, "reason": "ok", "returned_images": int(len(runtime.data.blocks))}
            )
            runtime.data.token_stream = runtime.module.stream_vision_chat_completions_tokens(
                http_client=runtime.engine.http_async_client,
                messages=runtime.data.openai_msgs,
            )
    except Exception as exc:  # noqa: BLE001
        runtime.data.vision_generation_meta.update(
            {
                "enabled": bool(getattr(settings, "VISION_RAG_GENERATION_ENABLED", False)),
                "used": False,
                "reason": f"vision_generation_exception:{str(exc)[:160]}",
            }
        )
        runtime.data.token_stream = None


async def stream_generation_tokens(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:

    if runtime.data.token_stream is None:
        runtime.data.token_stream = runtime.data.chain.astream(runtime.data.generation_inputs)

    try:
        async for runtime.data.token in runtime.data.token_stream:
            if not runtime.data.token:
                continue
            runtime.data.token_text = (
                runtime.data.token if isinstance(runtime.data.token, str) else str(runtime.data.token)
            )

            if runtime.data.buffered_parts is not None:
                runtime.data.buffered_parts.append(runtime.data.token_text)
                continue

            runtime.data.full_response += runtime.data.token_text
            yield {"type": "token", "data": {"content": runtime.data.token_text}}
    finally:
        runtime.data.close_token_stream = getattr(runtime.data.token_stream, "aclose", None)
        if callable(runtime.data.close_token_stream):
            await runtime.data.close_token_stream()

    if runtime.data.buffered_parts is not None:
        runtime.data.raw_generated = "".join(runtime.data.buffered_parts)
        runtime.data.full_response = (
            runtime.module.redact_text(runtime.data.raw_generated)
            if runtime.data.pii_on
            else runtime.data.raw_generated
        )

    runtime.data.llm_invocation_meta: dict[str, Any] = {}
    runtime.data.get_last_invocation_meta = getattr(runtime.data.llm, "get_last_invocation_meta", None)


async def capture_llm_invocation(runtime: StandardStreamState) -> None:
    if callable(runtime.data.get_last_invocation_meta):
        try:
            runtime.data.llm_invocation_meta = dict(runtime.data.get_last_invocation_meta() or {})
        except Exception:
            runtime.data.llm_invocation_meta = {}
    runtime.data.llm_model_used = (
        str(runtime.data.llm_invocation_meta.get("selected_model") or "").strip() or runtime.data.base_llm_model_name
    )


def _verify_text_claims(runtime: StandardStreamState) -> None:
    runtime.data.claims = runtime.module.split_into_claims(
        runtime.data.full_response,
        max_claims=runtime.data.claim_check_max_claims,
    )
    runtime.data.claim_check_total = len(runtime.data.claims)
    runtime.data.kept = []
    for claim in runtime.data.claims:
        verification = runtime.module.verify_claim_with_fallback(
            claim,
            runtime.data.evidence_text,
            verifier_mode=runtime.data.claim_verifier_mode,
            verifier_enable_contradiction_check=runtime.data.claim_verifier_enable_contradiction_check,
            use_nli_fallback=bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)),
            nli_provider=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"),
            nli_model_name=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or ""),
            nli_timeout_sec=float(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", 8) or 8),
        )
        if verification.supported:
            runtime.data.kept.append(claim)
            continue
        runtime.data.claim_check_removed += 1
        if len(runtime.data.claim_check_removed_reasons) < 64:
            diagnostics = verification.diagnostics if isinstance(verification.diagnostics, dict) else {}
            runtime.data.claim_check_removed_reasons.append(
                {
                    "claim": str(claim or "")[:300],
                    "reason_code": str(diagnostics.get("reason_code") or diagnostics.get("reason") or "unsupported")[
                        :120
                    ],
                    "contradiction_type": (
                        str(diagnostics.get("contradiction_type"))[:120]
                        if diagnostics.get("contradiction_type") is not None
                        else None
                    ),
                }
            )
    cleaned = "\n".join(runtime.data.kept).strip()
    runtime.data.full_response = cleaned or runtime.module._UNABLE_TO_ANSWER_MESSAGE


def _structured_claim_citations(runtime: StandardStreamState) -> list[dict[str, Any]]:
    citations = runtime.data.citations[: max(0, int(runtime.data.top_k or 0))]
    return [
        {
            "document_id": citation.get("document_id"),
            "chunk_id": citation.get("chunk_id"),
            "page_number": citation.get("page_number"),
            "relevance_score": citation.get("relevance_score"),
        }
        for citation in citations
    ]


def _verify_structured_claims(runtime: StandardStreamState) -> None:
    runtime.data.structured_citations = _structured_claim_citations(runtime)
    runtime.data.parsed, runtime.data._meta = runtime.module.parse_and_repair_structured_output(
        runtime.data.full_response,
        preset=runtime.data.structured_preset,
        fallback_answer=runtime.module._UNABLE_TO_ANSWER_MESSAGE,
        fallback_citations=runtime.data.structured_citations,
    )
    runtime.data.scrubbed, runtime.data.scrub_meta = runtime.module.scrub_structured_output_visible_evidence_only(
        runtime.data.parsed,
        evidence_text=runtime.data.evidence_text,
        max_claims=runtime.data.claim_check_max_claims,
        verifier_mode=runtime.data.claim_verifier_mode,
        verifier_enable_contradiction_check=runtime.data.claim_verifier_enable_contradiction_check,
        use_nli_fallback=bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)),
        nli_provider=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"),
        nli_model_name=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or ""),
        nli_timeout_sec=float(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", 8) or 8),
    )
    if isinstance(runtime.data.scrub_meta, dict):
        runtime.data.claim_check_total = int(runtime.data.scrub_meta.get("claims_total") or 0)
        runtime.data.claim_check_removed = int(runtime.data.scrub_meta.get("claims_removed") or 0)
        reasons = runtime.data.scrub_meta.get("claim_check_removed_reasons")
        if isinstance(reasons, list):
            runtime.data.claim_check_removed_reasons = [item for item in reasons if isinstance(item, dict)][:64]
    try:
        if (
            isinstance(runtime.data.scrubbed, dict)
            and isinstance(runtime.data.scrubbed.get("answer"), str)
            and not str(runtime.data.scrubbed.get("answer") or "").strip()
        ):
            runtime.data.scrubbed["answer"] = runtime.module._UNABLE_TO_ANSWER_MESSAGE
    except Exception as exc:
        runtime.module.logger.debug(runtime.module._RAG_ENGINE_FALLBACK_LOG_MESSAGE, exc)
    runtime.data.full_response = json.dumps(runtime.data.scrubbed, ensure_ascii=False, separators=(",", ":"))


async def verify_claims(runtime: StandardStreamState) -> None:
    if not runtime.data.claim_check_applied:
        return
    runtime.data.evidence_text = runtime.data.context_for_model
    if runtime.data.claim_check_mode == "text":
        _verify_text_claims(runtime)
    elif runtime.data.claim_check_mode == "structured":
        _verify_structured_claims(runtime)


async def apply_output_guard_and_init_evidence(runtime: StandardStreamState) -> None:

    if runtime.data.output_guard_enabled:
        try:
            from app.rag.safety import get_output_guard

            runtime.data.guard = get_output_guard()
            runtime.data.guard_result = await runtime.data.guard.check(runtime.data.full_response)
            runtime.data.output_guard_result = {
                "enabled": True,
                "action": str(runtime.data.guard_result.action or "allow"),
                "score": float(runtime.data.guard_result.score or 0.0),
                "matched_rules": list(runtime.data.guard_result.matched_rules or []),
            }
            if runtime.data.guard_result.action == "block":
                runtime.data.blocked_message = "Response withheld by safety filter."
                if runtime.data.structured_output:
                    runtime.data.full_response = json.dumps(
                        {"answer": runtime.data.blocked_message, "citations": []}, ensure_ascii=False
                    )
                else:
                    runtime.data.full_response = runtime.data.blocked_message
        except Exception as exc:  # noqa: BLE001
            runtime.module.logger.warning("Output guard failed open: %s", str(exc)[:160])
            runtime.data.output_guard_result = {
                "enabled": True,
                "action": "allow",
                "score": 0.0,
                "matched_rules": [],
                "error": str(exc)[:160],
            }

    runtime.data.claim_evidence: list[dict[str, Any]] = []
    if not runtime.data.structured_output:
        try:
            runtime.data.claim_evidence = runtime.module.build_claim_evidence_map(
                runtime.data.full_response,
                evidence_chunks=runtime.data.docs,
                max_claims=runtime.data.claim_check_max_claims if runtime.data.claim_check_configured else 24,
                verifier_mode=runtime.data.claim_verifier_mode,
                verifier_enable_contradiction_check=runtime.data.claim_verifier_enable_contradiction_check,
                use_nli_fallback=bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)),
                nli_provider=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"),
                nli_model_name=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or ""),
                nli_timeout_sec=float(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", 8) or 8),
            )
        except Exception:
            runtime.data.claim_evidence = []

    runtime.data.faithfulness_meta: dict[str, Any] = {
        "score": None,
        "supported_claims": 0,
        "total_claims": 0,
        "unsupported_claims": [],
        "method": "claim_support_ratio",
    }


async def score_evidence_and_confidence(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    if bool(getattr(settings, "FAITHFULNESS_SCORE_ENABLED", True)):
        runtime.data.evidence_text = "\n".join(
            [
                str(getattr(d, "page_content", "") or "")
                for d in (runtime.data.docs or [])
                if str(getattr(d, "page_content", "") or "").strip()
            ]
        )
        runtime.data.max_evidence_chars = max(
            0, int(getattr(settings, "FAITHFULNESS_SCORE_MAX_EVIDENCE_CHARS", 24_000) or 24_000)
        )
        if runtime.data.max_evidence_chars and len(runtime.data.evidence_text) > runtime.data.max_evidence_chars:
            runtime.data.evidence_text = runtime.data.evidence_text[: runtime.data.max_evidence_chars]
        runtime.data.faithfulness_meta = runtime.module.compute_faithfulness_score(
            answer=str(runtime.data.full_response or ""),
            evidence_text=runtime.data.evidence_text,
            max_claims=max(1, int(getattr(settings, "FAITHFULNESS_SCORE_MAX_CLAIMS", 24) or 24)),
            verifier_mode=runtime.data.claim_verifier_mode,
            verifier_enable_contradiction_check=bool(runtime.data.claim_verifier_enable_contradiction_check),
            use_nli_fallback=bool(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_ENABLED", False)),
            nli_provider=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_PROVIDER", "none") or "none"),
            nli_model_name=str(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_MODEL", "") or ""),
            nli_timeout_sec=float(getattr(settings, "RAG_CLAIM_NLI_VERIFIER_TIMEOUT_SEC", 8) or 8),
        )
    if runtime.data.source_identification_answer_used:
        runtime.data.faithfulness_meta = {
            "score": 1.0,
            "supported_claims": 1,
            "total_claims": 1,
            "unsupported_claims": [],
            "method": "deterministic_source_identification",
        }

    runtime.data.sentence_citations_inline_enabled = bool(getattr(settings, "SENTENCE_CITATIONS_INLINE_ENABLED", False))
    runtime.data.sentence_citations_inline_used = False
    runtime.data.sentence_citations_inline_count = 0
    runtime.data.sentence_citations_inline_style = (
        str(getattr(settings, "SENTENCE_CITATIONS_INLINE_STYLE", "appendix") or "appendix").strip().lower()
        or "appendix"
    )
    if runtime.data.sentence_citations_inline_style not in {"appendix", "inline"}:
        runtime.data.sentence_citations_inline_style = "appendix"
    runtime.data.sentence_citations_inline_fallback_reason: str | None = None
    runtime.data.confidence_meta = runtime.module.compute_confidence_score(
        faithfulness_score=runtime.data.faithfulness_meta.get("score"),
        claim_total=runtime.data.faithfulness_meta.get("total_claims"),
        claim_supported=runtime.data.faithfulness_meta.get("supported_claims"),
        evidence_gap=None,
    )
    try:
        runtime.data.faithfulness_score_value = (
            float(runtime.data.faithfulness_meta.get("score"))
            if runtime.data.faithfulness_meta.get("score") is not None
            else None
        )
    except Exception:
        runtime.data.faithfulness_score_value = None
    if (
        runtime.data.corrective_enabled
        and runtime.data.faithfulness_score_value is not None
        and runtime.data.faithfulness_score_value < runtime.data.corrective_min_faithfulness
    ):
        if "faithfulness_lt_min" not in runtime.data.corrective_reason_codes:
            runtime.data.corrective_reason_codes.append("faithfulness_lt_min")
        yield {
            "type": "quality_warning",
            "data": {
                "kind": "faithfulness_low",
                "faithfulness_score": round(runtime.data.faithfulness_score_value, 3),
                "threshold": round(float(runtime.data.corrective_min_faithfulness), 3),
                "corrective_available": True,
            },
        }


async def render_claim_citations(runtime: StandardStreamState) -> None:

    # Optional: inline per-claim citations (only safe when claim-check produced a claim list).
    if (
        not runtime.data.structured_output
        and runtime.data.sentence_citations_inline_enabled
        and runtime.data.sentence_citations_inline_style == "inline"
    ):
        if runtime.data.claim_check_mode == "text":
            runtime.data.inline_text, runtime.data.rendered_count = runtime.module.render_sentence_citations_inline(
                runtime.data.claim_evidence,
                max_items=max(
                    0,
                    int(getattr(settings, "SENTENCE_CITATIONS_INLINE_MAX_ITEMS", 8) or 8),
                ),
                max_evidence_per_claim=max(
                    1,
                    int(
                        getattr(
                            settings,
                            "SENTENCE_CITATIONS_INLINE_MAX_EVIDENCE_PER_CLAIM",
                            2,
                        )
                        or 2
                    ),
                ),
            )
            if runtime.data.inline_text:
                runtime.data.full_response = runtime.data.inline_text
                runtime.data.sentence_citations_inline_used = True
                runtime.data.sentence_citations_inline_count = int(runtime.data.rendered_count or 0)
            else:
                runtime.data.sentence_citations_inline_style = "appendix"
                runtime.data.sentence_citations_inline_fallback_reason = "inline_render_empty"
        else:
            runtime.data.sentence_citations_inline_style = "appendix"
            runtime.data.sentence_citations_inline_fallback_reason = "claim_check_not_text"


async def append_image_citations(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:

    # Step 4.5: Append cited images as inline Markdown (non-structured output only).
    if (
        not runtime.data.structured_output
        and runtime.data.citations
        and bool(settings.SHOW_IMAGE_IN_ANSWER)
        and settings.IMAGE_APPEND_MAX > 0
    ):
        runtime.data.image_urls: list[str] = []
        for runtime.data.c in runtime.data.citations:
            if not runtime.data.c.get("has_image"):
                continue
            runtime.data.url = runtime.data.c.get("img_url")
            if not isinstance(runtime.data.url, str) or not runtime.data.url.strip():
                continue
            if runtime.data.url in runtime.data.image_urls:
                continue
            runtime.data.image_urls.append(runtime.data.url)
            if len(runtime.data.image_urls) >= settings.IMAGE_APPEND_MAX:
                break

        if runtime.data.image_urls:
            runtime.data.images_md_parts = ["\n\n---\n\n### Related Images\n"]
            for runtime.data.i, runtime.data.url in enumerate(runtime.data.image_urls, 1):
                runtime.data.images_md_parts.append(f"![Cited Image {runtime.data.i}]({runtime.data.url})")
            runtime.data.images_md = "\n\n".join(runtime.data.images_md_parts) + "\n"
            runtime.data.images_md_safe = (
                runtime.module.redact_text(runtime.data.images_md) if runtime.data.pii_on else runtime.data.images_md
            )
            runtime.data.full_response += runtime.data.images_md_safe
            if not runtime.data.claim_check_applied:
                yield {"type": "token", "data": {"content": runtime.data.images_md_safe}}


async def flush_response_and_init_costs(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:

    if (
        not runtime.data.structured_output
        and runtime.data.sentence_citations_inline_enabled
        and runtime.data.sentence_citations_inline_style == "appendix"
    ):
        runtime.data.suffix_md, runtime.data.rendered_count = runtime.module.render_sentence_citations_markdown(
            runtime.data.claim_evidence,
            max_items=max(0, int(getattr(settings, "SENTENCE_CITATIONS_INLINE_MAX_ITEMS", 8) or 8)),
            max_evidence_per_claim=max(
                1, int(getattr(settings, "SENTENCE_CITATIONS_INLINE_MAX_EVIDENCE_PER_CLAIM", 2) or 2)
            ),
        )
        if runtime.data.suffix_md:
            runtime.data.suffix_md_safe = (
                runtime.module.redact_text(runtime.data.suffix_md) if runtime.data.pii_on else runtime.data.suffix_md
            )
            runtime.data.full_response += runtime.data.suffix_md_safe
            runtime.data.sentence_citations_inline_used = True
            runtime.data.sentence_citations_inline_count = int(runtime.data.rendered_count or 0)
            if not runtime.data.claim_check_applied:
                yield {"type": "token", "data": {"content": runtime.data.suffix_md_safe}}

    if runtime.data.buffered_parts is not None:
        yield {"type": "token", "data": {"content": runtime.data.full_response}}

    # Cost attribution per request.
    #
    # Keep this PII-safe: only numeric counters and model identifiers.
    runtime.data.answer_chars = len(runtime.data.full_response or "")
    runtime.data.answer_tokens = runtime.module.num_tokens_from_string(runtime.data.full_response or "")
    runtime.data.question_tokens = runtime.module.num_tokens_from_string(runtime.data.question or "")
    runtime.data.prompt_overhead = int(settings.COST_PROMPT_OVERHEAD_TOKENS)
    runtime.data.prompt_tokens_est = (
        runtime.module.num_tokens_from_string(runtime.data.history_text or "")
        + runtime.module.num_tokens_from_string(runtime.data.context or "")
        + runtime.data.question_tokens
        + max(0, runtime.data.prompt_overhead)
    )
    runtime.data.llm_source = "mock" if bool(getattr(settings, "LLM_MOCK_ENABLED", False)) else "estimate"

    runtime.data.embed_query_tokens = 0
    runtime.data.embed_query_chars = 0


async def measure_embedding_costs(runtime: StandardStreamState) -> None:
    for runtime.data.q in runtime.data.retrieval_per_query or []:
        if not isinstance(runtime.data.q, dict):
            continue
        try:
            runtime.data.embed_query_tokens += int(runtime.data.q.get("query_tokens") or 0)
        except Exception as exc:
            runtime.module.logger.debug(runtime.module._RAG_ENGINE_FALLBACK_LOG_MESSAGE, exc)
        try:
            runtime.data.embed_query_chars += int(runtime.data.q.get("query_chars") or 0)
        except Exception as exc:
            runtime.module.logger.debug(runtime.module._RAG_ENGINE_FALLBACK_LOG_MESSAGE, exc)

    runtime.data.rerank_elapsed_sec: float | None = None


async def measure_rerank_and_record_metrics(runtime: StandardStreamState) -> None:
    for runtime.data.c in runtime.data.citations or []:
        if not isinstance(runtime.data.c, dict):
            continue
        runtime.data.v = runtime.data.c.get("rerank_elapsed_sec")
        if runtime.data.v is None:
            continue
        try:
            runtime.data.fv = float(runtime.data.v)
        except Exception:
            runtime.module.logger.debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if runtime.data.fv < 0:
            continue
        if runtime.data.rerank_elapsed_sec is None or runtime.data.fv > runtime.data.rerank_elapsed_sec:
            runtime.data.rerank_elapsed_sec = runtime.data.fv

    runtime.data.cost_attribution = {
        "schema": "mimirq.cost_attribution.v1",
        "llm": {
            "model_used": runtime.data.llm_model_used,
            "prompt_tokens": int(runtime.data.prompt_tokens_est),
            "completion_tokens": int(runtime.data.answer_tokens),
            "total_tokens": int(runtime.data.prompt_tokens_est + runtime.data.answer_tokens),
            "source": runtime.data.llm_source,
        },
        "embeddings": {
            "provider": str(getattr(settings, "EMBEDDING_PROVIDER", "") or ""),
            "model": str(getattr(settings, "EMBEDDING_MODEL", "") or ""),
            "query_count": int(len(runtime.data.retrieval_per_query or [])),
            "query_chars": int(runtime.data.embed_query_chars),
            "query_tokens": int(runtime.data.embed_query_tokens),
            "source": "estimate",
        },
        "retrieval": {
            "elapsed_sec": round(float(runtime.data.retrieval_elapsed or 0.0), 3),
            "rerank_elapsed_sec": round(float(runtime.data.rerank_elapsed_sec), 3)
            if runtime.data.rerank_elapsed_sec is not None
            else None,
            "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
            "query_count": int(len(runtime.data.retrieval_per_query or [])),
        },
    }
    # Metrics JSONL (rag_trace) keeps a nested shape for UI tooling.
    runtime.data.rag_trace_payload["cost_attribution"] = runtime.data.cost_attribution

    runtime.data.rag_trace_payload["claim_check"] = {
        "enabled": bool(runtime.data.claim_check_configured),
        "mode": runtime.data.claim_check_mode,
        "verifier_mode": runtime.data.claim_verifier_mode,
        "verifier_enable_contradiction_check": bool(runtime.data.claim_verifier_enable_contradiction_check),
        "applied": bool(runtime.data.claim_check_applied),
        "max_claims": int(runtime.data.claim_check_max_claims),
        "claims_total": int(runtime.data.claim_check_total),
        "claims_removed": int(runtime.data.claim_check_removed),
        "removed_reasons": runtime.data.claim_check_removed_reasons,
    }
    runtime.data.rag_trace_payload["faithfulness"] = {
        "enabled": bool(getattr(settings, "FAITHFULNESS_SCORE_ENABLED", True)),
        "score": runtime.data.faithfulness_meta.get("score"),
        "supported_claims": int(runtime.data.faithfulness_meta.get("supported_claims") or 0),
        "total_claims": int(runtime.data.faithfulness_meta.get("total_claims") or 0),
        "unsupported_claims": list(runtime.data.faithfulness_meta.get("unsupported_claims") or []),
        "method": str(runtime.data.faithfulness_meta.get("method") or "claim_support_ratio"),
        "sentence_citations_count": int(len(runtime.data.claim_evidence or [])),
        "sentence_citations_inline_enabled": bool(runtime.data.sentence_citations_inline_enabled),
        "sentence_citations_inline_style": str(runtime.data.sentence_citations_inline_style),
        "sentence_citations_inline_used": bool(runtime.data.sentence_citations_inline_used),
        "sentence_citations_inline_count": int(runtime.data.sentence_citations_inline_count or 0),
        "sentence_citations_inline_fallback_reason": runtime.data.sentence_citations_inline_fallback_reason,
    }
    # Prometheus SLI metrics (PII-safe; low-cardinality by default).
    try:
        from app.rag.metrics_sli import observe_rag_sli

        observe_rag_sli(
            tenant_id=str(runtime.data.tenant_id) if runtime.data.tenant_id else None,
            dataset_id=str(runtime.data.dataset_id) if runtime.data.dataset_id else None,
            citations_count=len(runtime.data.citations),
            retrieval_elapsed_sec=float(runtime.data.retrieval_elapsed or 0.0),
            rerank_elapsed_sec=(
                float(runtime.data.rerank_elapsed_sec) if runtime.data.rerank_elapsed_sec is not None else None
            ),
            has_error=bool(runtime.data.retrieval_errors),
        )
    except Exception as exc:
        runtime.module.logger.debug(runtime.module._RAG_ENGINE_FALLBACK_LOG_MESSAGE, exc)
    runtime.module.log_metrics(runtime.data.rag_trace_payload)


async def enqueue_online_evaluation(runtime: StandardStreamState) -> None:
    # Best-effort: sampled online evaluation (async, PII-minimal outputs).
    try:
        from app.services.online_eval_service import maybe_enqueue_online_eval

        maybe_enqueue_online_eval(
            tenant_id=runtime.data.tenant_id,
            dataset_id=runtime.data.dataset_id,
            request_id=str(runtime.data.request_id),
            answer=str(runtime.data.full_response or ""),
            contexts=[str(getattr(d, "page_content", "") or "") for d in (runtime.data.docs or [])],
            retrieval_mode=str(runtime.data.mode_used or "") or None,
            citations_count=int(len(runtime.data.citations or [])),
        )
    except Exception as exc:
        runtime.module.logger.debug(runtime.module._RAG_ENGINE_FALLBACK_LOG_MESSAGE, exc)


GENERATION_OPERATIONS = (
    StreamOperation(prepare_generation, streams=True),
    StreamOperation(prepare_vision_generation, streams=False),
    StreamOperation(stream_generation_tokens, streams=True),
    StreamOperation(capture_llm_invocation, streams=False),
    StreamOperation(verify_claims, streams=False),
    StreamOperation(apply_output_guard_and_init_evidence, streams=False),
    StreamOperation(score_evidence_and_confidence, streams=True),
    StreamOperation(render_claim_citations, streams=False),
    StreamOperation(append_image_citations, streams=True),
    StreamOperation(flush_response_and_init_costs, streams=True),
    StreamOperation(measure_embedding_costs, streams=False),
    StreamOperation(measure_rerank_and_record_metrics, streams=False),
    StreamOperation(enqueue_online_evaluation, streams=False),
)

__all__ = ["GENERATION_OPERATIONS"]
