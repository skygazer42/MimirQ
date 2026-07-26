"""Shared logger and constants for the document processor support modules."""
from app.rag.core.logging import get_logger

logger = get_logger("parsing.document_processor")
_PROCESSOR_CLEANUP_LOG_MESSAGE = "Ignoring non-critical processor cleanup failure: %s"


def _log_processor_fallback(context: str, exc: BaseException) -> None:
    logger.debug("processor fallback failed in %s: %s", context, exc, exc_info=True)


MIMIRQ_PARSE_DIRNAME = '.mimirq_parse'
REDACTED_MASK = '[REDACTED]'
# Redaction placeholder, not a credential.
SECRET_MASK = '[SECRET]'  # noqa: S105
