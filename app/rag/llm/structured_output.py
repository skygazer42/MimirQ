from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.rag.core.text import parse_json_from_text


class _StructuredBase(BaseModel):
    answer: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)


class FAQStructuredOutput(_StructuredBase):
    qa_pairs: list[dict[str, Any]] = Field(default_factory=list)


class SummaryStructuredOutput(_StructuredBase):
    bullets: list[str] = Field(default_factory=list)
    summary: str = ""


class ActionItemsStructuredOutput(_StructuredBase):
    actions: list[dict[str, Any]] = Field(default_factory=list)


STRUCTURED_OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "faq": FAQStructuredOutput,
    "summary": SummaryStructuredOutput,
    "action_items": ActionItemsStructuredOutput,
}


STRUCTURED_OUTPUT_INSTRUCTIONS: dict[str, str] = {
    "faq": (
        "Output JSON only, structure: "
        '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "..."}],'
        '"qa_pairs": [{"question": "string", "answer": "string"}]}'
        " No extra text."
    ),
    "summary": (
        "Output JSON only, structure: "
        '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "..."}],'
        '"bullets": ["point 1", "point 2"], "summary": "concise summary"}'
        " No extra text."
    ),
    "action_items": (
        "Output JSON only, structure: "
        '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "..."}],'
        '"actions": [{"item": "action", "owner": "responsible person", "due": "deadline"}]}'
        " No extra text."
    ),
}

_DEFAULT_STRUCTURED_OUTPUT_INSTRUCTIONS = (
    "Please return JSON only, structure: "
    '{"answer": "string", "citations": [{"document_id": "...", "chunk_id": "...", '
    '"page_number": null, "relevance_score": 0.0}]} '
    "No extra text."
)


def normalize_structured_preset_key(preset: str | None) -> str:
    key = str(preset or "").strip().lower()
    return key if key in STRUCTURED_OUTPUT_MODELS else ""


def build_structured_output_instructions(preset: str | None) -> str:
    key = normalize_structured_preset_key(preset)
    return STRUCTURED_OUTPUT_INSTRUCTIONS.get(key, _DEFAULT_STRUCTURED_OUTPUT_INSTRUCTIONS)


def build_structured_abstain_payload(
    *,
    preset: str | None,
    answer: str,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    key = normalize_structured_preset_key(preset)
    payload: dict[str, Any] = {
        "answer": str(answer or ""),
        "citations": list(citations or []),
    }
    if key == "faq":
        payload["qa_pairs"] = []
    elif key == "summary":
        payload["bullets"] = []
        payload["summary"] = ""
    elif key == "action_items":
        payload["actions"] = []
    return payload


def _repair_with_schema(
    data: dict[str, Any] | None,
    *,
    preset: str | None,
    fallback_answer: str,
    fallback_citations: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    key = normalize_structured_preset_key(preset)
    merged = build_structured_abstain_payload(
        preset=key,
        answer=fallback_answer,
        citations=fallback_citations,
    )
    if isinstance(data, dict):
        merged.update(data)

    model = STRUCTURED_OUTPUT_MODELS.get(key)
    if model is None:
        return merged, not isinstance(data, dict)

    try:
        validated = model.model_validate(merged)
        repaired = not isinstance(data, dict) or dict(validated.model_dump(mode="json")) != data
        return dict(validated.model_dump(mode="json")), repaired
    except ValidationError:
        fallback_validated = model.model_validate(
            build_structured_abstain_payload(
                preset=key,
                answer=fallback_answer,
                citations=fallback_citations,
            )
        )
        return dict(fallback_validated.model_dump(mode="json")), True


def parse_and_repair_structured_output(
    text: str,
    *,
    preset: str | None,
    fallback_answer: str,
    fallback_citations: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed, meta = parse_json_from_text(text, expected="object")
    payload, repaired = _repair_with_schema(
        parsed if isinstance(parsed, dict) else None,
        preset=preset,
        fallback_answer=fallback_answer,
        fallback_citations=fallback_citations,
    )
    out_meta = dict(meta or {})
    out_meta["schema_key"] = normalize_structured_preset_key(preset) or "default"
    out_meta["repaired"] = bool(repaired)
    out_meta["fallback_used"] = not bool(out_meta.get("ok"))
    return payload, out_meta


__all__ = [
    "ActionItemsStructuredOutput",
    "FAQStructuredOutput",
    "SummaryStructuredOutput",
    "STRUCTURED_OUTPUT_INSTRUCTIONS",
    "STRUCTURED_OUTPUT_MODELS",
    "build_structured_abstain_payload",
    "build_structured_output_instructions",
    "normalize_structured_preset_key",
    "parse_and_repair_structured_output",
]
