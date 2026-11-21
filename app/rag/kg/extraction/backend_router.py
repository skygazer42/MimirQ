from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from app.infrastructure.config import settings
from app.infrastructure.model_policy import reject_retired_provider

if TYPE_CHECKING:
    from app.rag.kg.extraction.heuristic_extractor import HeuristicExtractor
    from app.rag.kg.extraction.processor import EventProcessor

    ExtractionProcessor: TypeAlias = EventProcessor | HeuristicExtractor

_VALID_BACKENDS = {"llm", "heuristic"}


@dataclass(slots=True)
class ExtractionBackendSelection:
    backend: str
    processor: "ExtractionProcessor"
    fallback_reason: str | None = None


def normalize_extraction_backend(requested_backend: str | None) -> str:
    backend = settings.KG_EXTRACTION_BACKEND if requested_backend is None else requested_backend
    raw = backend.strip().lower()
    reject_retired_provider(raw, capability="kg_extraction")
    if raw in _VALID_BACKENDS:
        return raw
    raise ValueError(f"Unknown KG extraction backend: {raw!r}")


def resolve_extraction_backend(
    *, llm_processor: "EventProcessor", requested_backend: str | None = None
) -> ExtractionBackendSelection:
    backend = normalize_extraction_backend(requested_backend)
    if backend == "heuristic":
        from app.rag.kg.extraction.heuristic_extractor import HeuristicExtractor

        return ExtractionBackendSelection(backend="heuristic", processor=HeuristicExtractor())
    return ExtractionBackendSelection(backend="llm", processor=llm_processor)
