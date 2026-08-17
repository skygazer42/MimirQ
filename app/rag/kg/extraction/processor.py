"""
Simplified event processor: call LLM to extract events and entities from chunk text.
"""
import json
from typing import Any

from app.core.config import settings
from app.models.document import DocumentChunk
from app.rag.kg.extraction.parser import EntityValueParser
from app.rag.kg.utils import get_logger
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole

logger = get_logger("kg.extract.processor")


def _build_context(sections: list[DocumentChunk]) -> str:
    context_parts = []
    for idx, chunk in enumerate(sections, 1):
        page = getattr(chunk, "page_number", None)
        prefix = "[Target" if idx == 1 else f"[Context {idx - 1}"
        if page is not None:
            prefix += f" p{page}"
        prefix += "]"
        context_parts.append(f"{prefix} {chunk.content}")
    max_chars = int(getattr(settings, "KG_EXTRACT_CONTEXT_MAX_CHARS", 8000) or 8000)
    max_chars = max(1000, min(max_chars, 200_000))
    return "\n\n".join(context_parts)[:max_chars]


def _positive_int(value: int, *, default_min: int = 1) -> int:
    return max(default_min, int(value or 0))


def _extraction_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "schema_version": {"type": "string"},
                        "event_schema": {"type": "string"},
                        "entities": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"type": "string"},
                                    "description": {"type": "string"},
                                    "role": {"type": "string"},
                                    "weight": {"type": "number", "minimum": 0, "maximum": 1},
                                    "evidence_quote": {"type": "string"},
                                    "source_span": {
                                        "type": "object",
                                        "properties": {
                                            "source": {"type": "string"},
                                            "start_char": {"type": "integer"},
                                            "end_char": {"type": "integer"},
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "required": ["title", "summary"],
                },
            }
        },
    }


def _render_prompt(
    prompt_template: str | None,
    *,
    context: str,
    schema: dict[str, Any],
    max_events: int,
    max_entities: int,
) -> str:
    if prompt_template:
        schema_hint = json.dumps(schema, ensure_ascii=False)
        template_vars = {
            "context": context,
            "schema": schema_hint,
            "max_events": max_events,
            "max_entities": max_entities,
            "max_entities_per_event": max_entities,
        }
        try:
            return prompt_template.format_map(template_vars)
        except Exception:
            # Best-effort: avoid failing extraction due to template formatting issues.
            return f"{prompt_template}\n\n{context}"
    return (
        f"Read the following text chunks and extract up to {max_events} important events. "
        "Return JSON only. Each event should have title, summary (50-200 words) "
        f"and an entity list (up to {max_entities} items).\n"
        "\n"
        "Evidence requirements:\n"
        "- Each entity should include evidence_quote: an exact substring from the [Target] chunk that mentions the entity.\n"
        "- evidence_quote MUST be copied verbatim (no paraphrase).\n"
        f"{context}"
    )


def _coerce_entity_input(ent: Any) -> tuple[str, str, str, Any, Any, str, dict[str, Any]]:
    if isinstance(ent, dict):
        source_span = ent.get("source_span") if isinstance(ent.get("source_span"), dict) else {}
        return (
            ent.get("name") or "",
            ent.get("type") or "unknown",
            ent.get("description") or "",
            ent.get("role") or None,
            ent.get("weight"),
            ent.get("evidence_quote") or "",
            source_span,
        )
    return (str(ent), "unknown", "", None, None, "", {})


def _build_entity_payload(
    processor: "EventProcessor",
    *,
    name: str,
    entity_type: str,
    description: str,
    role: Any,
    weight: Any,
    evidence_quote: str,
    source_span: dict[str, Any],
) -> tuple[tuple[str, str], dict[str, Any]] | None:
    if not name:
        return None
    normalized_name = processor.parser.normalize_name(name)
    normalized_type = processor.parser.normalize_type(entity_type)
    return (
        (normalized_type, normalized_name),
        {
            "name": name.strip(),
            "normalized_name": normalized_name,
            "type": normalized_type,
            "description": description.strip(),
            "role": str(role or "").strip() or None,
            "weight": weight if isinstance(weight, (int, float)) else None,
            "evidence_quote": str(evidence_quote or "").strip() or None,
            "evidence_source": str(source_span.get("source") or "").strip() or None,
            "evidence_start_char": source_span.get("start_char") if isinstance(source_span.get("start_char"), int) else None,
            "evidence_end_char": source_span.get("end_char") if isinstance(source_span.get("end_char"), int) else None,
        },
    )


def _merge_entity_payload(existing: dict[str, Any], *, description: str, role: Any, evidence_quote: str) -> None:
    new_desc = description.strip()
    if new_desc and len(new_desc) > len(str(existing.get("description") or "")):
        existing["description"] = new_desc
    if not str(existing.get("evidence_quote") or "").strip():
        existing["evidence_quote"] = str(evidence_quote or "").strip() or None
    if not existing.get("role") and role:
        existing["role"] = str(role or "").strip() or None


def _collect_event_entities(processor: "EventProcessor", entities_raw: Any) -> list[dict[str, Any]]:
    entity_map: dict[tuple[str, str], dict[str, Any]] = {}
    for ent in entities_raw or []:
        name, entity_type, description, role, weight, evidence_quote, source_span = _coerce_entity_input(ent)
        built = _build_entity_payload(
            processor,
            name=name,
            entity_type=entity_type,
            description=description,
            role=role,
            weight=weight,
            evidence_quote=evidence_quote,
            source_span=source_span,
        )
        if built is None:
            continue
        key, payload = built
        existing = entity_map.get(key)
        if existing is None:
            entity_map[key] = payload
            continue
        _merge_entity_payload(existing, description=description, role=role, evidence_quote=evidence_quote)
    return list(entity_map.values())


def _build_event_payload(processor: "EventProcessor", raw: dict[str, Any], *, chunk_id: str) -> dict[str, Any]:
    title = (raw.get("title") or "").strip()
    summary = (raw.get("summary") or "").strip()
    if not title:
        title = summary[:50] or "Event"
    return {
        "title": title,
        "summary": summary or title,
        "content": summary or title,
        "schema_version": str(raw.get("schema_version") or "").strip() or None,
        "event_schema": str(raw.get("event_schema") or "").strip() or None,
        "entities": _collect_event_entities(processor, raw.get("entities") or []),
        "chunk_id": chunk_id,
    }


class EventProcessor:
    """Core extraction logic."""

    def __init__(self, llm_client: BaseLLMClient, *, prompt_template: str | None = None):
        self.llm_client = llm_client
        self.parser = EntityValueParser()
        self.prompt_template = (prompt_template or "").strip() or None

    async def extract_from_sections(
        self,
        sections: list[DocumentChunk],
        batch_index: int,
        *,
        max_events: int = 3,
        max_entities_per_event: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Extract events from a list of chunks. Returns list of dicts:
        {"title": str, "summary": str, "content": str, "entities": [{"name":..., "type":...}, ...], "chunk_id": uuid}
        """
        if not sections:
            return []

        context = _build_context(sections)
        max_events_i = _positive_int(max_events)
        max_entities_i = _positive_int(max_entities_per_event)
        schema = _extraction_schema()
        prompt = _render_prompt(
            self.prompt_template,
            context=context,
            schema=schema,
            max_events=max_events_i,
            max_entities=max_entities_i,
        )
        messages = [LLMMessage(role=LLMRole.USER, content=prompt)]

        result = await self.llm_client.chat_with_schema(messages, response_schema=schema, temperature=0.2)
        events_data = result.get("events", []) if isinstance(result, dict) else []

        events: list[dict[str, Any]] = []
        chunk_id = str(sections[0].id)
        for raw in events_data:
            if not isinstance(raw, dict):
                continue
            events.append(_build_event_payload(self, raw, chunk_id=chunk_id))

        logger.info("Batch %s extracted %s events", batch_index, len(events))
        return events
