"""Shared constants and logger split out of ``app.rag.kg.api.routes``.

The routes module re-exports these names for backwards compatibility.
"""

from app.rag.core.logging import get_logger

# Keep the historical logger name so log output stays identical to the pre-split module.
logger = get_logger("app.rag.kg.api.routes")

KG_ENTITY_NOT_FOUND_DETAIL = "KG entity not found"
KG_API_FALLBACK_LOG_MESSAGE = "Ignoring non-critical KG API fallback failure: %s"
KG_EXTRACTION_ALREADY_QUEUED_DETAIL = "A KG extraction job is already pending for this document and option set"
KG_PIPELINE_CHUNKS_NOT_FOUND_DETAIL = "No chunks found for the selected pipeline version"
