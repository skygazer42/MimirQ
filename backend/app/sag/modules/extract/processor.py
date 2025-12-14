"""
Simplified event processor: call LLM to extract events and entities from chunk text.
"""
from typing import Any, Dict, List

from app.models.document import DocumentChunk
from app.sag.core.ai.base import BaseLLMClient
from app.sag.core.ai.models import LLMMessage, LLMRole
from app.sag.modules.extract.parser import EntityValueParser
from app.sag.utils import get_logger

logger = get_logger("sag.extract.processor")


class EventProcessor:
    """Core extraction logic."""

    def __init__(self, llm_client: BaseLLMClient):
        self.llm_client = llm_client
        self.parser = EntityValueParser()

    async def extract_from_sections(
        self, sections: List[DocumentChunk], batch_index: int
    ) -> List[Dict[str, Any]]:
        """
        Extract events from a list of chunks. Returns list of dicts:
        {"title": str, "summary": str, "content": str, "entities": [{"name":..., "type":...}, ...], "chunk_id": uuid}
        """
        if not sections:
            return []

        context_parts = []
        for idx, chunk in enumerate(sections, 1):
            context_parts.append(f"[Chunk {idx}] {chunk.content}")
        context = "\n\n".join(context_parts)[:8000]

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
                            "entities": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"},
                                        "type": {"type": "string"},
                                        "description": {"type": "string"},
                                    },
                                },
                            },
                        },
                        "required": ["title", "summary"],
                    },
                }
            },
        }

        prompt = (
            "Read the following text chunks and extract 2-3 important events. "
            "Return JSON only. Each event should have title, summary (50-200 words) "
            "and an entity list (name/type/description optional).\n"
            f"{context}"
        )
        messages = [LLMMessage(role=LLMRole.USER, content=prompt)]

        result = await self.llm_client.chat_with_schema(messages, response_schema=schema, temperature=0.2)
        events_data = result.get("events", []) if isinstance(result, dict) else []

        events: List[Dict[str, Any]] = []
        for raw in events_data:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            summary = (raw.get("summary") or "").strip()
            if not title:
                # fallback to first sentence
                title = summary[:50] or "Event"
            entities_raw = raw.get("entities") or []
            entities = []
            for ent in entities_raw:
                if isinstance(ent, dict):
                    name = ent.get("name") or ""
                    etype = ent.get("type") or "unknown"
                    desc = ent.get("description") or ""
                else:
                    name = str(ent)
                    etype = "unknown"
                    desc = ""
                if not name:
                    continue
                entities.append(
                    {
                        "name": name.strip(),
                        "normalized_name": self.parser.normalize_name(name),
                        "type": etype.strip(),
                        "description": desc.strip(),
                    }
                )

            events.append(
                {
                    "title": title,
                    "summary": summary or title,
                    "content": summary or title,
                    "entities": entities,
                    "chunk_id": str(sections[0].id),
                }
            )

        logger.info("Batch %s extracted %s events", batch_index, len(events))
        return events
