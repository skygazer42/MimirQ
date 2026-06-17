"""
Simplified event processor: call LLM to extract events and entities from chunk text.
"""
from typing import Any

from app.core.config import settings
from app.models.document import DocumentChunk
from app.rag.kg.extraction.parser import EntityValueParser
from app.rag.kg.utils import get_logger
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.models import LLMMessage, LLMRole

logger = get_logger("kg.extract.processor")


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

        context_parts = []
        for idx, chunk in enumerate(sections, 1):
            page = getattr(chunk, "page_number", None)
            if idx == 1:
                prefix = "[Target"
            else:
                prefix = f"[Context {idx - 1}"
            if page is not None:
                prefix += f" p{page}"
            prefix += "]"
            context_parts.append(f"{prefix} {chunk.content}")
        max_chars = int(getattr(settings, "KG_EXTRACT_CONTEXT_MAX_CHARS", 8000) or 8000)
        max_chars = max(1000, min(max_chars, 200_000))
        context = "\n\n".join(context_parts)[:max_chars]

        max_events_i = max(1, int(max_events or 0))
        max_entities_i = max(1, int(max_entities_per_event or 0))

        schema = {
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

        if self.prompt_template:
            schema_hint = __import__("json").dumps(schema, ensure_ascii=False)
            template_vars = {
                "context": context,
                "schema": schema_hint,
                "max_events": max_events_i,
                "max_entities": max_entities_i,
                "max_entities_per_event": max_entities_i,
            }
            try:
                prompt = self.prompt_template.format_map(template_vars)
            except Exception:
                # Best-effort: avoid failing extraction due to template formatting issues.
                prompt = f"{self.prompt_template}\n\n{context}"
        else:
            prompt = (
                f"Read the following text chunks and extract up to {max_events_i} important events. "
                "Return JSON only. Each event should have title, summary (50-200 words) "
                f"and an entity list (up to {max_entities_i} items).\n"
                "\n"
                "Evidence requirements:\n"
                "- Each entity should include evidence_quote: an exact substring from the [Target] chunk that mentions the entity.\n"
                "- evidence_quote MUST be copied verbatim (no paraphrase).\n"
                f"{context}"
            )
        messages = [LLMMessage(role=LLMRole.USER, content=prompt)]

        result = await self.llm_client.chat_with_schema(messages, response_schema=schema, temperature=0.2)
        events_data = result.get("events", []) if isinstance(result, dict) else []

        events: list[dict[str, Any]] = []
        for raw in events_data:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            summary = (raw.get("summary") or "").strip()
            schema_version = str(raw.get("schema_version") or "").strip() or None
            event_schema = str(raw.get("event_schema") or "").strip() or None
            if not title:
                # fallback to first sentence
                title = summary[:50] or "Event"
            entities_raw = raw.get("entities") or []
            entity_map: dict[tuple[str, str], dict[str, Any]] = {}
            for ent in entities_raw:
                if isinstance(ent, dict):
                    name = ent.get("name") or ""
                    etype = ent.get("type") or "unknown"
                    desc = ent.get("description") or ""
                    role = ent.get("role") or None
                    weight = ent.get("weight")
                    evidence_quote = ent.get("evidence_quote") or ""
                    source_span = ent.get("source_span") if isinstance(ent.get("source_span"), dict) else {}
                else:
                    name = str(ent)
                    etype = "unknown"
                    desc = ""
                    role = None
                    weight = None
                    evidence_quote = ""
                    source_span = {}
                if not name:
                    continue
                normalized_name = self.parser.normalize_name(name)
                normalized_type = self.parser.normalize_type(etype)
                key = (normalized_type, normalized_name)
                existing = entity_map.get(key)
                if existing is None:
                    entity_map[key] = {
                        "name": name.strip(),
                        "normalized_name": normalized_name,
                        "type": normalized_type,
                        "description": desc.strip(),
                        "role": str(role or "").strip() or None,
                        "weight": weight if isinstance(weight, (int, float)) else None,
                        "evidence_quote": str(evidence_quote or "").strip() or None,
                        "evidence_source": str(source_span.get("source") or "").strip() or None,
                        "evidence_start_char": source_span.get("start_char")
                        if isinstance(source_span.get("start_char"), int)
                        else None,
                        "evidence_end_char": source_span.get("end_char")
                        if isinstance(source_span.get("end_char"), int)
                        else None,
                    }
                else:
                    # Best-effort merge: keep longer description.
                    new_desc = desc.strip()
                    if new_desc and len(new_desc) > len(str(existing.get("description") or "")):
                        existing["description"] = new_desc
                    # Prefer a non-empty evidence quote.
                    eq = str(existing.get("evidence_quote") or "").strip()
                    if not eq:
                        existing["evidence_quote"] = str(evidence_quote or "").strip() or None
                    if not existing.get("role") and role:
                        existing["role"] = str(role or "").strip() or None

            events.append(
                {
                    "title": title,
                    "summary": summary or title,
                    "content": summary or title,
                    "schema_version": schema_version,
                    "event_schema": event_schema,
                    "entities": list(entity_map.values()),
                    "chunk_id": str(sections[0].id),
                }
            )

        logger.info("Batch %s extracted %s events", batch_index, len(events))
        return events
