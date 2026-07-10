
import asyncio
from typing import Any

from app.core.config import settings
from app.core.optional_deps import check_dependency, require_dependency
from app.models.document import DocumentChunk
from app.rag.kg.extraction.parser import EntityValueParser
from app.rag.kg.utils import get_logger

logger = get_logger("kg.extract.gliner")


class GLiNERExtractor:
    """
    Optional GLiNER-based extractor.

    This implementation is intentionally conservative for the first slice:
    - dependency is loaded lazily
    - if selected via router, it produces entity-only events
    - relation refinement stays in the default LLM pipeline
    """

    def __init__(self) -> None:
        self._model: Any | None = None
        self._parser = EntityValueParser()

    @staticmethod
    def is_available() -> bool:
        ok, _err = check_dependency("gliner", attr="GLiNER")
        return bool(ok)

    def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        module = require_dependency("gliner", feature="kg_extraction_gliner", pip_name="gliner")
        gliner_cls = module.GLiNER
        model_name = str(getattr(settings, "KG_GLINER_MODEL_NAME", "") or "").strip() or "urchade/gliner_multi_pii-v1"
        model = gliner_cls.from_pretrained(model_name)
        device = str(getattr(settings, "KG_GLINER_DEVICE", "cpu") or "cpu").strip().lower()
        if device and device != "cpu" and hasattr(model, "to"):
            model = model.to(device)
        self._model = model
        return model

    async def extract_entities(
        self,
        *,
        text: str,
        entity_types: list[str] | None = None,
        threshold: float | None = None,
    ) -> list[dict[str, Any]]:
        clean_text = str(text or "").strip()
        if not clean_text:
            return []

        labels = entity_types
        if not labels:
            raw = str(getattr(settings, "KG_GLINER_DEFAULT_ENTITY_TYPES", "") or "")
            labels = [x.strip() for x in raw.replace("\n", ",").split(",") if x.strip()]
        if not labels:
            labels = ["person", "organization", "location", "event"]

        score_threshold = float(
            getattr(settings, "KG_GLINER_ENTITY_THRESHOLD", 0.5) if threshold is None else threshold
        )

        model = self._ensure_model()
        raw_entities = await asyncio.to_thread(
            model.predict_entities,
            clean_text,
            labels,
            score_threshold,
        )
        out: list[dict[str, Any]] = []
        for ent in raw_entities or []:
            if not isinstance(ent, dict):
                continue
            name = str(ent.get("text") or "").strip()
            if not name:
                continue
            label = self._parser.normalize_type(str(ent.get("label") or "unknown"))
            score = float(ent.get("score") or 0.0)
            out.append(
                {
                    "name": name,
                    "normalized_name": self._parser.normalize_name(name),
                    "type": label,
                    "description": "",
                    "evidence_quote": name,
                    "score": score,
                }
            )
        return out

    async def extract_from_sections(
        self,
        sections: list[DocumentChunk],
        batch_index: int,
        *,
        max_events: int = 3,
        max_entities_per_event: int = 30,
    ) -> list[dict[str, Any]]:
        if not sections:
            return []
        target = sections[0]
        context = "\n\n".join(str(getattr(ch, "content", "") or "") for ch in sections).strip()
        entities = await self.extract_entities(text=context)
        if not entities:
            return []

        max_events_i = max(1, int(max_events or 0))
        max_entities_i = max(1, int(max_entities_per_event or 0))
        trimmed = entities[:max_entities_i]
        logger.info("Batch %s GLiNER extracted %s entities", batch_index, len(trimmed))

        return [
            {
                "title": "Extracted entities",
                "summary": "Entity candidates extracted by GLiNER backend",
                "content": "Entity candidates extracted by GLiNER backend",
                "entities": [
                    {
                        "name": e["name"],
                        "normalized_name": e["normalized_name"],
                        "type": e["type"],
                        "description": e.get("description") or "",
                        "evidence_quote": e.get("evidence_quote"),
                        "score": float(e.get("score") or 0.0),
                    }
                    for e in trimmed
                ],
                "chunk_id": str(getattr(target, "id", "") or ""),
            }
        ][:max_events_i]
