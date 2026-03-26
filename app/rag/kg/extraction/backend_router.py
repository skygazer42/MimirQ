from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.rag.kg.utils import get_logger

logger = get_logger("kg.extract.backend_router")

_VALID_BACKENDS = {"llm", "gliner", "hybrid"}


@dataclass(slots=True)
class ExtractionBackendSelection:
    backend: str
    processor: Any
    fallback_reason: str | None = None


def _normalized_backend(requested_backend: str | None) -> str:
    raw = str(requested_backend or getattr(settings, "KG_EXTRACTION_BACKEND", "llm") or "llm").strip().lower()
    if raw in _VALID_BACKENDS:
        return raw
    logger.warning("Unknown KG extraction backend '%s'; falling back to llm", raw)
    return "llm"


def resolve_extraction_backend(*, llm_processor: Any, requested_backend: str | None = None) -> ExtractionBackendSelection:
    backend = _normalized_backend(requested_backend)
    if backend == "llm":
        return ExtractionBackendSelection(backend="llm", processor=llm_processor)

    from app.rag.kg.extraction.gliner_extractor import GLiNERExtractor
    from app.rag.kg.extraction.hybrid_extractor import HybridExtractor

    if not bool(getattr(settings, "KG_GLINER_ENABLED", False)):
        logger.info("KG extraction backend=%s requested but KG_GLINER_ENABLED=false; using llm", backend)
        return ExtractionBackendSelection(backend="llm", processor=llm_processor, fallback_reason="gliner_disabled")

    if not GLiNERExtractor.is_available():
        logger.warning("KG extraction backend=%s requested but gliner dependency unavailable; using llm", backend)
        return ExtractionBackendSelection(
            backend="llm",
            processor=llm_processor,
            fallback_reason="gliner_dependency_missing",
        )

    if backend == "gliner":
        return ExtractionBackendSelection(backend="gliner", processor=GLiNERExtractor())

    return ExtractionBackendSelection(
        backend="hybrid",
        processor=HybridExtractor(llm_processor=llm_processor, gliner_extractor=GLiNERExtractor()),
    )
