from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.models.document import DocumentChunk
from app.rag.kg.extraction.gliner_extractor import GLiNERExtractor


class HybridExtractor:
    """
    Conservative hybrid extractor for phase-1 rollout.

    Flow:
    - Run GLiNER entity extraction first.
    - If no entities or low-confidence entities are present, fallback to LLM processor.
    - Otherwise return the GLiNER event payload.
    """

    def __init__(self, *, llm_processor: Any, gliner_extractor: GLiNERExtractor | None = None) -> None:
        self._llm_processor = llm_processor
        self._gliner = gliner_extractor or GLiNERExtractor()

    async def extract_from_sections(
        self,
        sections: list[DocumentChunk],
        batch_index: int,
        *,
        max_events: int = 3,
        max_entities_per_event: int = 30,
    ) -> list[dict[str, Any]]:
        gliner_events = await self._gliner.extract_from_sections(
            sections,
            batch_index,
            max_events=max_events,
            max_entities_per_event=max_entities_per_event,
        )
        if not gliner_events:
            return await self._llm_processor.extract_from_sections(
                sections,
                batch_index,
                max_events=max_events,
                max_entities_per_event=max_entities_per_event,
            )

        threshold = float(getattr(settings, "KG_HYBRID_LLM_THRESHOLD", 0.7) or 0.7)
        entities = gliner_events[0].get("entities") if isinstance(gliner_events[0], dict) else None
        has_low_confidence = False
        if isinstance(entities, list):
            for ent in entities:
                if not isinstance(ent, dict):
                    continue
                score = float(ent.get("score") or 1.0)
                if score < threshold:
                    has_low_confidence = True
                    break
        if has_low_confidence:
            return await self._llm_processor.extract_from_sections(
                sections,
                batch_index,
                max_events=max_events,
                max_entities_per_event=max_entities_per_event,
            )
        return gliner_events
